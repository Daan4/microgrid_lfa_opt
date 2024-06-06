import numpy as np
import math
import pandas as pd
from lib import calc_s, calculate_diesel_fuel_usage
from pyswarm import pso

# Example load and solar profiles to ensure some usage of the diesel generator
load_profile = None
# Solar profile for 1 kWp installed
solar_profile = None
# Zeroes indicating grid unavailability
grid_schedule = None
pv_data = None

CONVERTER_EFFICIENCY = 0.95
BATT_EFFICIENCY = 0.9  # 90% for charging and discharging
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/

BATT_COST_PER_KWH = 226  # € https://www.nrel.gov/docs/fy23osti/85332.pdf
PV_COST_PER_KW = 1600  # € https://www.solarreviews.com/blog/installing-commercial-solar-panels

GRID_AVAILABLE_HOURS = [1, 2, 3, 4, 5, 10, 11, 12, 13, 17, 18, 19, 20, 21]  # List of hours in which grid is available, example 0 means from 00:00 through 01:00


def objective(x):
    """"
    Objective function which estimates the system cost
    """
    return x[1] * BATT_COST_PER_KWH + PV_COST_PER_KW * x[0]


def constraint(x):
    """
    Contraint function which calculates the diesel fuel usage in a year for a given system sizing.
    """
    pv_size = x[0]  # installed kWp
    battery_size = x[1]  # kWh
    soc = 0.5 * battery_size  # State of Charge (starts at 50%)
    fuel_usage = 0

    index = load_p_data.index

    for dt in index:
        s_load = math.sqrt(load_p_data[dt]**2 + load_q_data[dt]**2)
        s_pv = pv_data[dt] * pv_size
        s_diesel = 0
        s_batt = 0

        if s_pv > s_load:
            # Overproduction of PV
            if soc <= battery_size - (s_pv - s_load) * (BATT_EFFICIENCY):
                # pv overproduction used to charge battery if there is space in the battery
                s_batt = -(s_pv - s_load)
            else:
                # pv overproduction wasted by curtailment
                s_pv = s_load
        elif s_pv < s_load:
            # Gap between pv and load is filled based on priority
            if soc > 0.2*battery_size + (s_load-s_pv) / (BATT_EFFICIENCY):
                # battery can be used while staying above 20% soc
                s_batt = s_load - s_pv
            elif dt.hour not in GRID_AVAILABLE_HOURS:
                # Grid not available, so gap will have to be made up with remaining battery (under 20% soc) + diesel genset
                if soc >= (s_load-s_pv) / (BATT_EFFICIENCY):
                    # Battery can be used while staying above 0 soc
                    s_batt = s_load - s_pv
                else:
                    # Battery cannot be used while staying above 0 soc. diesel generator kicks in and charges battery with remainder
                    s_diesel = max(250, s_load - s_pv)
                    s_diesel = min(750, s_diesel)
                    if s_diesel > s_load - s_pv:
                        s_batt = s_load - s_pv - s_diesel

        if s_diesel > 0:
            fuel_usage += calculate_diesel_fuel_usage(s_diesel)

        # adjust soc
        if s_batt >= 0:
            soc -= s_batt / BATT_EFFICIENCY
        else:
            soc -= s_batt * BATT_EFFICIENCY
        soc = min(soc, battery_size)
        soc = max(0, soc)

    #print(pv_size, battery_size, fuel_usage)

    if fuel_usage < 0.09*318242:
        return 1
    else:
        return -1


def optimize_swarm():
    xopt, fopt = pso(objective, [500, 500], [2000, 50000], f_ieqcons=constraint, debug=True)

    print("Optimization Result:")
    print(f"Optimal PV size: {xopt[0]}")
    print(f"Optimal Battery size: {xopt[1]}")
    print(f"Objective value: {fopt}\n")


if __name__ == "__main__":
    # Get power profile for 1 kWp installed pv
    data = pd.read_csv("data/irradiance.csv")
    solar_profile = np.array(data["ALLSKY_SFC_SW_DWN"] * PV_PRODUCTION_PER_KWP / data["ALLSKY_SFC_SW_DWN"].sum())

    # Get load data, converted to apparent power
    index = pd.date_range("2021-01-01 00:00", "2021-12-31 23:30", freq="30min")
    data = pd.read_csv("data/load_half_hourly.csv")
    load_p_data = pd.Series(data.kW.values, index).resample("1h").mean()
    load_q_data = pd.Series(data.kVAr.values, index).resample("1h").mean()
    load_s_data = calc_s(load_p_data, load_q_data)
    load_profile = load_s_data

    index = pd.date_range("2021-01-01 00:00", "2021-12-31 23:30", freq="1h")
    data = pd.read_csv("data/irradiance.csv")
    # Scale to match expected yearly production
    data["ALLSKY_SFC_SW_DWN"] = data["ALLSKY_SFC_SW_DWN"] * PV_PRODUCTION_PER_KWP / data["ALLSKY_SFC_SW_DWN"].sum()
    data = pd.Series(data["ALLSKY_SFC_SW_DWN"].values, index)
    # Apply inverter efficiency
    data = data * CONVERTER_EFFICIENCY
    pv_data = data

    # Set grid schedule
    #  Diesel generator is on between 0600-1030, 1400-1630, 2200-0030
    # hours shifted a bit due to using hourly pattern, but still 10 hours a day
    daily_pattern = [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0]
    grid_schedule = np.array(daily_pattern * 365)

    optimize_swarm()

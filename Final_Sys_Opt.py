import numpy as np
from scipy.optimize import least_squares
import math
import pandas as pd
from lib import calc_s

# Example load and solar profiles to ensure some usage of the diesel generator
load_profile = np.array([])
# Solar profile for 1 kWp installed
solar_profile = np.array([])
# Zeroes indicating grid unavailability
grid_schedule = np.array([])

converter_efficiency = 0.95
battery_efficiency = 0.9  # 90% for charging and discharging
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/


# Function to calculate the Loss of Load Probability and diesel generator hours needed
def objective(x):
    pv_size = x[0]  # installed kWp
    battery_size = x[1]  # kWh
    soc = 0.5 * battery_size  # State of Charge (starts at 50%)
    diesel_needed_hours = 0  # Number of hours diesel generator is needed
    pv_curtail_hours = 0  # Number of hours the pv is curtailed

    for t in range(len(load_profile)):
        # Calculate PV output based on normalised solar profile, pv_size.
        # Capped to load demand (no feed-in allowed)
        energy_pv = min(pv_size * solar_profile[t], load_profile[t])

        if grid_schedule[t] == 0:  # Grid disconnected
            energy_grid = 0
        else:
            energy_grid = max(0, load_profile[t] - energy_pv)

        # battery fills the gap
        energy_battery = load_profile[t] - energy_pv - energy_grid

        # update soc based on energy supplied
        if energy_battery >= 0:
            soc -= energy_battery / (battery_efficiency * converter_efficiency)
        else:
            soc -= energy_battery * (battery_efficiency * converter_efficiency)

        # cap soc, if soc is higher than pv should be curtailed
        if soc > battery_size:
            pv_curtail_hours += 1
        soc = min(soc, battery_size)

        # cap soc, if soc got below 0 it means the diesel generator is needed to fill the gap
        if soc < 0:
            diesel_needed_hours += 1

        soc = max(soc, 0)

    # output function chosen such that it minimizes diesel needed, pv curtailment, and battery sizing
    output = math.sqrt(diesel_needed_hours**2 + pv_curtail_hours**2)

    return float(diesel_needed_hours)


# Detailed debugging to check if optimizer changes the values
def debug_optimizer(result, initial_guess):
    print("Optimization Result:")
    print(f"Initial Guess: {initial_guess}")
    print(f"Optimal PV size: {result.x[0]}")
    print(f"Optimal Battery size: {result.x[1]}")
    print(f"Objective value: {result.fun}")
    print(f"Diesel needed hours: {result.fun[0]}")
    #print(f"PV curtail hours: {result.fun[1]}\n")


def optimize(initial_guess):
    # Define bounds for PV size and battery size
    bounds = [[0, 0], [np.inf, np.inf]]  # PV size and Battery size must be non-negative

    # Use the minimize function to find the optimal sizes
    result = least_squares(objective, initial_guess, bounds=bounds, method='trf', diff_step=1, loss='cauchy')

    # Debug output to ensure optimizer worked correctly
    debug_optimizer(result, initial_guess)


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
    load_profile = np.array(load_s_data.array)

    # Set grid schedule
    #  Diesel generator is on between 0600-1030, 1400-1630, 2200-0030
    # hours shifted a bit due to using hourly pattern, but still 10 hours a day
    daily_pattern = [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0]
    grid_schedule = np.array(daily_pattern * 365)

    # compare different starting guesses
    # optimize([100, 100])
    # optimize([10000, 10000])
    optimize([100, 100])
    # optimize([100000, 100000])

    # Initial result to try model with:
    # PV size 34.355 MWp ~$34 million cost assuming $1/Wp  https://www.solar.com/learn/solar-panel-cost/
    # battery size 666.322 MWh ~$92.5 million cost assuming $139/kWh
    # seems reasonable? Let's try it out!
    # https://atb.nrel.gov/electricity/2023/utility-scale_battery_storage stating $338 dollar per kwh in 21 for 60MW 600MWh battery which is similar to hours

import pypsa
import math
import pandas as pd
import matplotlib.pyplot as plt
from lib import calculate_electricity_costs, calculate_diesel_fuel_usage, calculate_soc

# Parameters
PV_INSTALLED_CAPACITY = 34355  # [kiloWatt-peak] ; this value can be varied to optimise the system
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/
CONVERTER_EFFICIENCY = 0.95  # efficiency for power converters https://www.edn.com/efficiency-calculations-for-power-converters/ https://www.energysavingtrust.org.uk/sites/default/files/reports/Solar%20inverters.pdf
BATT_EFFICIENCY = 0.9  # 10% lost on charging, 10% on discharging... seems reasonable but need source, includes converter losses
BATT_NOM_ENERGY = 666322  # [kWh] energy capacity
#BATT_NOM_POWER = BATT_NOM_ENERGY / 10  # [kW] power limit > assume max power stored is 10 hours
# nominal power is no issue with this large of a battery we can assume it covers any instantaneous power asked by plant
BATT_SOC_INITIAL = BATT_NOM_ENERGY/2  # [kWh] initial state of charge
GRID_AVAILABLE_HOURS = [1, 2, 3, 4, 5, 10, 11, 12, 13, 17, 18, 19, 20, 21]  # List of hours in which grid is available, example 0 means from 00:00 through 01:00

# Model Validation
# Example control function
# pyPSA optimisation
# optimisation by using pf output as the objective function!!!
# add in option to have random chance of grid failure based on real numbers


def get_load_data():
    """
    Get the load data from the csv and resample it from 30 min data to hourly data.

    :return: Returns a tuple with the series index, active power series, and reactive power series
    """

    index = pd.date_range("2021-01-01 00:00", "2021-12-31 23:30", freq="30min")
    data = pd.read_csv("data/load_half_hourly.csv")

    load_p_data = pd.Series(data.kW.values, index).resample("1h").mean()
    load_q_data = pd.Series(data.kVAr.values, index).resample("1h").mean()

    return load_p_data, load_q_data


def get_pv_data():
    """
    Get the hourly pv production data based on the installed kW-peak capacity of solar panels & irradiation data
    The pv production is formed by scaling the irradiance profile to match this value

    :return: Returns a series with power production per hour
    """
    index = pd.date_range("2021-01-01 00:00", "2021-12-31 23:30", freq="1h")
    data = pd.read_csv("data/irradiance.csv")
    # Scale to match expected yearly production
    data["ALLSKY_SFC_SW_DWN"] = data["ALLSKY_SFC_SW_DWN"] * PV_INSTALLED_CAPACITY * PV_PRODUCTION_PER_KWP / data["ALLSKY_SFC_SW_DWN"].sum()
    data = pd.Series(data["ALLSKY_SFC_SW_DWN"].values, index)
    # Apply inverter efficiency
    data = data * CONVERTER_EFFICIENCY
    return data


def plot_load_data():
    (load_p_data, load_q_data) = get_load_data()

    plt.figure()
    plt.plot(load_p_data, label="Active Power Demand")
    plt.plot(load_q_data, label="Reactive Power Demand")
    plt.plot(load_p_data + load_q_data, label="Apparent Power Demand")
    plt.xlabel("Time")
    plt.ylabel("Power [kW/kVAr/kVA]")
    plt.legend(loc="best")
    plt.grid(True)
    plt.title("Load Power Demand")
    plt.show()


def initialize_network(strategy):
    network = pypsa.Network()

    (load_p_data, load_q_data) = get_load_data()
    pv_data = get_pv_data()

    network.snapshots = load_p_data.index

    (p_set_diesel, q_set_diesel, p_set_battery, q_set_battery, p_set_pv, q_set_pv) = calculate_setpoints(load_p_data, load_q_data, pv_data, strategy)

    # AC bus
    # 400V
    network.add("Bus", "AC bus", v_nom=400)

    # PV
    network.add("Generator", "PV", bus="AC bus",
                control="PQ",
                p_set=p_set_pv,
                q_set=q_set_pv)

    # Battery
    network.add("StorageUnit", "BESS", bus="AC bus",
                control="PQ",
                p_set=p_set_battery,
                q_set=q_set_battery)

    # Diesel generator
    network.add("Generator", "Diesel generator", bus="AC bus",
                control="PQ",
                p_set=p_set_diesel,
                q_set=q_set_diesel)

    # Plant load
    # Modelled as a time varying load
    network.add("Load", "Plant load", bus="AC bus",
                p_set=load_p_data,
                q_set=load_q_data)

    # Grid connection
    # Modelled as a slack generator
    network.add("Generator", "Grid", bus="AC bus", control="Slack")

    return network


def calculate_setpoints(load_p_data, load_q_data, pv_data, strategy):
    """
    Calculate the diesel, pv, and battery setpoints based on the load demand and pv production
    Setpoints are calculated in apparent power and split to active/reactive power at the end.

    Diesel is rated at max 750kVA and can supply a minimum of 250kVA
    Grid is only available on this daily schedule
    daily_pattern = [0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0]

    :param load_p_data: load active power
    :param load_q_data: load reactive power
    :param pv_data: pv power production (can be split across active/reactive as needed)
    :return: p and q setpoints for diesel generator, BESS and PV
    """
    if strategy == 'priority':
        return calculate_setpoints_priority(load_p_data, load_q_data, pv_data)
    else:
        raise NotImplemented(f"Strategy {strategy} is not implemented.")


def calculate_setpoints_priority(load_p_data, load_q_data, pv_data):
    """
    Implement priority-based control strategy

    Priority 1: PV
    Priority 2: BESS (only if soc > 20%)
    Priority 3: Grid
    Priority 4: BESS (soc <= 20%)
    Priority 5: genset

    """
    # track the battery state of charge in kWh
    soc = BATT_SOC_INITIAL

    index = load_p_data.index

    p_set_diesel = []
    q_set_diesel = []
    p_set_battery = []
    q_set_battery = []
    p_set_pv = []
    q_set_pv = []

    for dt in index:
        s_load = math.sqrt(load_p_data[dt]**2 + load_q_data[dt]**2)
        s_pv = pv_data[dt]
        s_diesel = 0
        s_batt = 0

        if s_pv > s_load:
            # Overproduction of PV
            if soc <= BATT_NOM_ENERGY - (s_pv - s_load) * (BATT_EFFICIENCY * CONVERTER_EFFICIENCY):
                # pv overproduction used to charge battery if there is space in the battery
                s_batt = -(s_pv - s_load)
            else:
                # pv overproduction wasted by curtailment
                s_pv = s_load
        elif s_pv < s_load:
            # Gap between pv and load is filled based on priority
            if soc > 0.2*BATT_NOM_ENERGY + (s_load-s_pv) / (BATT_EFFICIENCY * CONVERTER_EFFICIENCY):
                # battery can be used while staying above 20% soc
                s_batt = s_load - s_pv
            elif dt.hour not in GRID_AVAILABLE_HOURS:
                # Grid not available, so gap will have to be made up with remaining battery (under 20% soc) + diesel genset
                if soc >= (s_load-s_pv) / (BATT_EFFICIENCY * CONVERTER_EFFICIENCY):
                    # Battery can be used while staying above 0 soc
                    s_batt = s_load - s_pv
                else:
                    # Battery cannot be used while staying above 0 soc. diesel generator kicks in and charges battery with remainder
                    s_diesel = min(250, s_load - s_pv)
                    s_diesel = max(750, s_diesel)
                    if s_diesel > s_load - s_pv:
                        s_batt = s_load - s_pv - s_diesel

        # adjust soc
        if s_batt >= 0:
            soc -= s_batt / (BATT_EFFICIENCY * CONVERTER_EFFICIENCY)
        else:
            soc -= s_batt * (BATT_EFFICIENCY * CONVERTER_EFFICIENCY)
        soc = min(soc, BATT_NOM_ENERGY)
        soc = max(0, soc)

        # calculate p and q setpoints for each component
        p_set_pv.append(s_pv / s_load * load_p_data[dt])
        q_set_pv.append(s_pv / s_load * load_q_data[dt])
        p_set_battery.append(s_batt / s_load * load_p_data[dt])

        q_set_battery.append(s_batt / s_load * load_q_data[dt])
        p_set_diesel.append(s_diesel / s_load * load_p_data[dt])
        q_set_diesel.append(s_diesel / s_load * load_q_data[dt])
        pass

    p_set_diesel = pd.Series(p_set_diesel, index)
    q_set_diesel = pd.Series(q_set_diesel, index)
    p_set_battery = pd.Series(p_set_battery, index)
    q_set_battery = pd.Series(q_set_battery, index)
    p_set_pv = pd.Series(p_set_pv, index)
    q_set_pv = pd.Series(q_set_pv, index)

    return p_set_diesel, q_set_diesel, p_set_battery, q_set_battery, p_set_pv, q_set_pv


def validate_results():
    """
    Check if the project goals are met

    :return:
    """


if __name__ == "__main__":
    network = initialize_network('priority')

    network.pf()

    gen_p = network.generators_t.p
    gen_q = network.generators_t.q

    load_p = network.loads_t.p
    load_q = network.loads_t.q

    store_p = network.storage_units_t.p
    store_q = network.storage_units_t.q

    # Plotting
    # Plot Active Power
    plt.figure(0)
    plt.plot(gen_p["Diesel generator"], label="Diesel Generator")
    plt.plot(gen_p["Grid"], label="Grid")
    plt.plot(gen_p["PV"], label="PV")
    plt.plot(store_p["BESS"], label="BESS")
    plt.plot(load_p, label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("P [kW]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Active Power")

    # Plot Reactive Power
    plt.figure(1)
    plt.plot(gen_q["Diesel generator"], label="Diesel Generator")
    plt.plot(gen_q["Grid"], label="Grid")
    plt.plot(gen_q["PV"], label="PV")
    plt.plot(store_q["BESS"], label="BESS")
    plt.plot(load_q, label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("Q [kVAr]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Reactive Power")

    # Plot Apparent Power
    plt.figure(2)
    plt.plot(gen_p["Diesel generator"] + gen_q["Diesel generator"], label="Diesel Generator")
    plt.plot(gen_p["Grid"] + gen_q["Grid"], label="Grid")
    plt.plot(gen_p["PV"] + gen_q["PV"], label="PV")
    plt.plot(store_p["BESS"] + store_q["BESS"], label="BESS")
    plt.plot(load_p + load_q, label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("S [kVA]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Apparent Power")

    # Plot State of Charge
    plt.figure(3)
    plt.plot(calculate_soc(store_p, store_q, BATT_NOM_ENERGY, BATT_SOC_INITIAL, BATT_EFFICIENCY*CONVERTER_EFFICIENCY), label="BESS")
    plt.xlabel("Time (hour")
    plt.ylabel("State of Charge [%]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("State of Charge")

    validate_results()

    print("Energy Consumed from Grid")
    print(f"Active Energy: {gen_p['Grid'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Grid'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['Grid'].sum() / 1000 + gen_q['Grid'].sum() / 1000:.0f} MVAh")
    print(f"Electricity Bill: €{calculate_electricity_costs(gen_p['Grid'], gen_q['Grid']):.0f}\n")

    print("Energy Consumed from Diesel Generator: ")
    print(f"Active Energy: {gen_p['Diesel generator'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Diesel generator'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['Diesel generator'].sum() / 1000 + gen_q['Diesel generator'].sum() / 1000:.0f} MVAh")
    print(f"Fuel Usage: {calculate_diesel_fuel_usage(gen_p['Diesel generator'], gen_q['Diesel generator']):.0f} l")
    print(f"Fuel Cost: €{calculate_diesel_fuel_usage(gen_p['Diesel generator'], gen_q['Diesel generator'])*0.81:.0f}\n")

    print("Energy Consumed from PV: ")
    print(f"Active Energy: {gen_p['PV'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['PV'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['PV'].sum() / 1000 + gen_q['PV'].sum() / 1000:.0f} MVAh\n")

    print("Energy Consumed by Load: ")
    print(f"Active Energy: {load_p['Plant load'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {load_q['Plant load'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {load_p['Plant load'].sum() / 1000 + load_q['Plant load'].sum() / 1000:.0f} MVAh")

    plt.show()

import pypsa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from lib import calculate_electricity_costs, calculate_diesel_fuel_usage, calculate_soc

# Parameters
PV_INSTALLED_CAPACITY = 100  # [kiloWatt-peak] ; this value can be varied to optimise the system
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/
CONVERTER_EFFICIENCY = 0.95  # efficiency for power converters https://www.edn.com/efficiency-calculations-for-power-converters/ https://www.energysavingtrust.org.uk/sites/default/files/reports/Solar%20inverters.pdf
BATT_EFFICIENCY = 0.9  # 10% lost on charging, 10% on discharging... seems reasonable but need source
BATT_NOM_POWER = 100  # [kW] power limit
BATT_NOM_ENERGY = 1000  # [kWh] energy capacity
BATT_SOC_INITIAL = 500  # [kWh] initial state of charge


# Model Validation
# Example control function
# pyPSA optimisation


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


def initialize_network():
    network = pypsa.Network()

    (load_p_data, load_q_data) = get_load_data()
    pv_data = get_pv_data()

    network.snapshots = load_p_data.index

    (p_set_diesel, q_set_diesel, p_set_battery, q_set_battery, p_set_pv, q_set_pv) = calculate_setpoints(load_p_data, load_q_data, pv_data)

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
    # Rated capacity 750kVA
    # Minimum load 250kVA
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


def calculate_setpoints(load_p_data, load_q_data, pv_data):
    """
    Calculate the diesel p and q setpoints based on the load shedding scheme. In the times where there is no grid, the diesel generator supplies the load power demand
    Diesel generator is on between 0600-1030, 1400-1630, 2200-0030

    :param load_p_data: load active power
    :param load_q_data: load reactive power
    :param pv_data: pv power production (can be split across active/reactive as needed)
    :return: p and q setpoints for diesel generator, BESS and PV
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
        mins = dt.hour * 60 + dt.minute
        if mins >= 6 * 60 and mins <= 10 * 60 + 30 or mins >= 14 * 60 and mins <= 16 * 60 + 30 or (
                mins >= 22 * 60 or mins <= 30):
            # Grid available
            pass
        else:
            # Grid not available
            pass


    p_set_diesel = pd.Series(p_set_diesel, index)
    q_set_diesel = pd.Series(q_set_diesel, index)
    p_set_battery = pd.Series(p_set_battery, index)
    q_set_battery = pd.Series(q_set_battery, index)
    p_set_pv = pd.Series(p_set_pv, index)
    q_set_pv = pd.Series(q_set_pv, index)

    return p_set_diesel, q_set_diesel, p_set_battery, q_set_battery, p_set_pv, q_set_pv, soc


if __name__ == "__main__":
    network = initialize_network()

    network.pf()

    gen_p = network.generators_t.p
    gen_q = network.generators_t.q

    load_p = network.loads_t.p
    load_q = network.loads_t.q

    store_p = network.storage_units_t.p
    store_q = network.storage_units_t.q

    bus_vmag = network.buses_t.v_mag_pu
    bus_vang = network.buses_t.v_ang * 180 / np.pi

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
    plt.plot(store_soc, label="BESS")
    plt.xlabel("Time (hour")
    plt.ylabel("State of Charge [%]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("State of Charge")

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

import pypsa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Parameters
PV_INSTALLED_CAPACITY = 100  # [kiloWatt-peak] ; this value can be varied to optimise the system
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/
CONVERTER_EFFICIENCY = 0.95  # efficiency for power converters https://www.edn.com/efficiency-calculations-for-power-converters/ https://www.energysavingtrust.org.uk/sites/default/files/reports/Solar%20inverters.pdf
BATT_EFFICIENCY = 0.9  # 10% lost on charging, 10% on discharging... to find source...
BATT_NOM_POWER = 100  # [kW] power limit
BATT_NOM_ENERGY = 1000  # [kWh] energy capacity


# TODO: how to model control, discuss modelling approach with Hatim,
# Figure out how state of charge works for the battery
# How to do validation? SHould i try to find some yearly output for actual solar panel installation in johannesburg
# and see if its similar?
# Example control function
# Question, i decided to use 1 single AC bus for now, with converter efficiencies worked into the pv output and batt
# efficiencies, because they only transmit active power not reactive power. Is there a trick to this or is this fine?


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

    (p_set_diesel, q_set_diesel, p_set_battery, q_set_battery) = calculate_setpoints(load_p_data, load_q_data, pv_data)

    # AC bus
    # 400V
    network.add("Bus", "AC bus", v_nom=400)

    # PV
    network.add("Generator", "PV", bus="AC bus", p_set=pv_data, control="PQ")

    # Battery
    network.add("StorageUnit", "BESS", bus="AC bus", control="PQ", p_set=1,
                q_set=q_set_battery, p_nom=BATT_NOM_POWER, max_hppours=BATT_NOM_ENERGY/BATT_NOM_POWER,
                efficiency_store=BATT_EFFICIENCY*CONVERTER_EFFICIENCY,
                efficiency_dispatch=BATT_EFFICIENCY*CONVERTER_EFFICIENCY,
                state_of_charge_initial=500)

    # Diesel generator
    # Rated capacity 750kVA
    # Minimum load 250kVA
    network.add("Generator", "Diesel generator", bus="AC bus", control="PQ", p_set=p_set_diesel, q_set=q_set_diesel)

    # Plant load
    # Modelled as a time varying load
    network.add("Load", "Plant load", bus="AC bus", p_set=load_p_data, q_set=load_q_data)

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
    :return: tuple(p_setpoint, q_setpoint)
    """

    index = load_p_data.index

    p_set_diesel = []
    q_set_diesel = []

    for dt in index:
        mins = dt.hour * 60 + dt.minute
        if mins >= 6 * 60 and mins <= 10 * 60 + 30 or mins >= 14 * 60 and mins <= 16 * 60 + 30 or (
                mins >= 22 * 60 or mins <= 30):
            p_set_diesel.append(0)
            q_set_diesel.append(0)
        else:
            p_set_diesel.append(load_p_data.get(dt))
            q_set_diesel.append(load_q_data.get(dt))

    p_set_diesel = pd.Series(p_set_diesel, index)
    q_set_diesel = pd.Series(q_set_diesel, index)

    p_set_battery = pd.Series(0, index)
    q_set_battery = pd.Series(0, index)

    return p_set_diesel, q_set_diesel, p_set_battery, q_set_battery


if __name__ == "__main__":
    network = initialize_network()

    network.determine_network_topology()
    subnetworks = network.sub_networks

    network.pf()

    gen_p = network.generators_t.p
    gen_q = network.generators_t.q

    load_p = network.loads_t.p
    load_q = network.loads_t.q

    store_p = network.storage_units_t.p
    store_q = network.storage_units_t.q
    store_soc = network.storage_units_t.state_of_charge

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
    print(f"Apparent Energy: {gen_p['Grid'].sum() / 1000 + gen_q['Grid'].sum() / 1000:.0f} MVAh\n")

    print("Energy Consumed from Diesel Generator: ")
    print(f"Active Energy: {gen_p['Diesel generator'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Diesel generator'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['Diesel generator'].sum() / 1000 + gen_q['Diesel generator'].sum() / 1000:.0f} MVAh\n")

    print("Energy Consumed from PV: ")
    print(f"Active Energy: {gen_p['PV'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['PV'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['PV'].sum() / 1000 + gen_q['PV'].sum() / 1000:.0f} MVAh\n")

    print("Energy Consumed by Load: ")
    print(f"Active Energy: {load_p['Plant load'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {load_q['Plant load'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {load_p['Plant load'].sum() / 1000 + load_q['Plant load'].sum() / 1000:.0f} MVAh")

    plt.show()

import pypsa
import numpy as np
import matplotlib.pyplot as plt
from lib import *


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


def plot_load_data():
    """
    Plot the load data
    """
    (load_p_data, load_q_data) = get_load_data()

    plt.figure()
    plt.plot(load_p_data, label="Active Power Demand")
    plt.plot(load_q_data, label="Reactive Power Demand")
    plt.plot(calc_s(load_p_data, load_q_data), label="Apparent Power Demand")
    plt.xlabel("Time")
    plt.ylabel("Power [kW/kVAr/kVA]")
    plt.legend(loc="best")
    plt.grid(True)
    plt.title("Load Power Demand")
    plt.show()


def initialize_network():
    """
    Initialize the pypsa network

    :return: network
    """

    _network = pypsa.Network()

    (load_p_data, load_q_data) = get_load_data()

    _network.snapshots = load_p_data.index

    (p_set_diesel, q_set_diesel) = calculate_diesel_setpoints(load_p_data, load_q_data)

    # AC bus
    # 400V
    _network.add("Bus", "AC bus", v_nom=400)

    # Diesel generator
    _network.add("Generator", "Diesel generator", bus="AC bus", control="PQ", p_set=p_set_diesel, q_set=q_set_diesel)

    # Plant load
    _network.add("Load", "Plant load", bus="AC bus", p_set=load_p_data, q_set=load_q_data)

    # Grid connection
    # Modelled as a slack generator, since feeding back into the grid is not allowed.
    _network.add("Generator", "Grid", bus="AC bus", control="Slack")

    return _network


def calculate_diesel_setpoints(load_p_data, load_q_data):
    """
    Calculate the diesel p and q setpoints based on the load shedding scheme.
    In the times where there is no grid, the diesel generator supplies the load power demand
    Diesel generator is on between 0600-1030, 1400-1630, 2200-0030

    :param load_p_data: load active power
    :param load_q_data: load reactive power
    :return: tuple(p_setpoint, q_setpoint)
    """

    index = load_p_data.index

    p_set_diesel = []
    q_set_diesel = []

    for dt in index:
        mins = dt.hour*60 + dt.minute
        if mins >= 6*60 and mins <= 10*60+30 or mins >= 14*60 and mins <= 16*60+30 or (mins >= 22*60 or mins <= 30):
            p_set_diesel.append(0)
            q_set_diesel.append(0)
        else:
            p_set_diesel.append(load_p_data.get(dt))
            q_set_diesel.append(load_q_data.get(dt))

    p_set_diesel = pd.Series(p_set_diesel, index)
    q_set_diesel = pd.Series(q_set_diesel, index)

    return p_set_diesel, q_set_diesel


if __name__ == "__main__":
    network = initialize_network()

    network.determine_network_topology()
    subnetworks = network.sub_networks

    network.pf()

    gen_p = network.generators_t.p
    gen_q = network.generators_t.q

    load_p = network.loads_t.p
    load_q = network.loads_t.q

    links_p = network.links_t.p0

    bus_vmag = network.buses_t.v_mag_pu
    bus_vang = network.buses_t.v_ang * 180 / np.pi

    # Plotting
    # Plot Active Power
    plt.figure(0)
    plt.plot(gen_p["Diesel generator"], label="Diesel Generator")
    plt.plot(gen_p["Grid"], label="Grid")
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
    plt.plot(load_q, label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("Q [kVAr]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Reactive Power")

    # Plot Apparent Power
    plt.figure(2)
    plt.plot(calc_s(gen_p["Diesel generator"], gen_q["Diesel generator"]), label="Diesel Generator")
    plt.plot(calc_s(gen_p["Grid"], gen_q["Grid"]), label="Grid")
    plt.plot(calc_s(load_p, load_q), label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("S [kVA]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Apparent Power")

    print("Energy Consumed from Grid")
    print(f"Active Energy: {gen_p['Grid'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Grid'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(gen_p['Grid'].sum()/1000, gen_q['Grid'].sum()/1000):.0f} MVAh")
    print(f"Electricity Bill: €{calculate_electricity_costs(gen_p['Grid'], gen_q['Grid']):.0f}\n")

    # https: // www.energy.gov.za / files / esources / petroleum / September2021 / Fuel - Price - History.pdf
    # average fuel cost calculated as:
    print("Energy Consumed from Diesel Generator: ")
    print(f"Active Energy: {gen_p['Diesel generator'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Diesel generator'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(gen_p['Diesel generator'].sum()/1000, gen_q['Diesel generator'].sum()/1000):.0f} MVAh")
    print(f"Fuel Usage: {calculate_diesel_fuel_usage(calc_s(gen_p['Diesel generator'], gen_q['Diesel generator'])):.0f} l")
    print(f"Fuel Cost: €{calculate_diesel_fuel_usage(calc_s(gen_p['Diesel generator'], gen_q['Diesel generator']))*0.81:.0f}\n")

    print("Energy Consumed by Load: ")
    print(f"Active Energy: {load_p['Plant load'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {load_q['Plant load'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(load_p['Plant load'].sum()/1000, load_q['Plant load'].sum()/1000):.0f} MVAh")

    plt.show()

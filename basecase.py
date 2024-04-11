import pypsa
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt


network = pypsa.Network()


def get_load_data():
    """
    Get the load data from the csv and resample it from 30 min data to hourly data.

    :return: Returns a tuple with the series index, active power series, and reactive power series
    """

    index = pd.date_range("2021-01-01 00:00", "2021-12-31 23:30", freq="30min")
    data = pd.read_csv("data/load_half_hourly.csv")

    load_p_data = pd.Series(data.kW.values, index).resample("1h").mean()
    load_q_data = pd.Series(data.kVAr.values, index).resample("1h").mean()

    return load_p_data.index, load_p_data, load_q_data


def plot_load_data():
    (index, load_p_data, load_q_data) = get_load_data()

    plt.figure()
    plt.plot(load_p_data, label="Active Power Demand")
    plt.plot(load_q_data, label="Reactive Power Demand")
    plt.plot(load_p_data+load_q_data, label="Apparent Power Demand")
    plt.xlabel("Time")
    plt.ylabel("Power [W/VAr/VA]")
    plt.legend(loc="best")
    plt.grid(True)
    plt.title("Load Power Demand")
    plt.show()


def initialize_network():
    (index, load_p_data, load_q_data) = get_load_data()

    network.snapshots = index

    (diesel_p_set, diesel_q_set) = calculate_diesel_setpoints(load_p_data, load_q_data)

    # AC bus
    # 400V
    network.add("Bus", "AC bus", v_nom=400)

    # Diesel generator
    # Rated capacity 750kVA
    # Minimum load 250kVA
    # Takes over from
    network.add("Generator", "Diesel generator", bus="AC bus", p_set=50, q_set=50, control="PQ")

    # Plant load
    # Modelled as a time varying load
    network.add("Load", "Plant load", bus="AC bus", p_set=load_p_data, q_set=load_q_data)

    # Grid connection
    # Modelled as a slack generator, since feeding back into the grid is not allowed.
    network.add("Generator", "Grid", bus="AC bus", control="Slack", p_set=0)

    return network



# Calculate the diesel p and q setpoints based on the load shedding scheme. In the times where there is no grid, the diesel generator supplies the load power demand
# Diesel generator is on between 0600-1030, 1400-1630, 2200-0030
def calculate_diesel_setpoints(load_p_data, load_q_data):
    pass


if __name__ == "__main__":
    plot_load_data()
    # network = initialize_network()
    #
    # network.determine_network_topology()
    # subnetworks = network.sub_networks
    #
    # network.pf()
    #
    # gen_p = network.generators_t.p
    # gen_q = network.generators_t.q
    #
    # load_p = network.loads_t.p
    # load_q = network.loads_t.q
    #
    # links_p = network.links_t.p0
    #
    # bus_vmag = network.buses_t.v_mag_pu
    # bus_vang = network.buses_t.v_ang * 180 / np.pi

    pass

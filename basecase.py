import pypsa
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt


network = pypsa.Network()


def initialize_network():
    index = pd.date_range("2021-02-01 00:30", "2021-02-21 19:00", freq="30T")
    data = pd.read_csv("data/load.csv")

    load_p_data = pd.Series(data.kW.values, index)
    load_q_data = pd.Series(data.kVAr.values, index)

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

    pass

import pypsa
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt

network = pypsa.Network()


def initialize_components():
    # AC bus
    network.add("Bus", "AC bus", v_nom=400)

    # DC bus
    network.add("Bus", "DC bus", v_nom=48, carrier="DC")

    # Diesel generator
    network.add("Generator", "Diesel generator", bus="AC bus", p_set=100, control="PQ")

    # Plant load
    network.add("Load", "Plant load", bus="AC bus", p_set=100)

    # PV
    network.add("Generator", "PV", bus="DC bus")

    # BESS
    network.add("StorageUnit", "BESS", bus="DC bus")

    # AC-DC Converter
    network.add("Link", "AC-DC Converter", bus0="DC bus", bus1="AC bus")

    return network


if __name__ == "__main__":
    network = initialize_components()

    pass

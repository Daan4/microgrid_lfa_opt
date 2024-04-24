import pypsa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


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
    (load_p_data, load_q_data) = get_load_data()

    plt.figure()
    plt.plot(load_p_data, label="Active Power Demand")
    plt.plot(load_q_data, label="Reactive Power Demand")
    plt.plot(load_p_data+load_q_data, label="Apparent Power Demand")
    plt.xlabel("Time")
    plt.ylabel("Power [kW/kVAr/kVA]")
    plt.legend(loc="best")
    plt.grid(True)
    plt.title("Load Power Demand")
    plt.show()


def initialize_network():
    network = pypsa.Network()

    (load_p_data, load_q_data) = get_load_data()

    network.snapshots = load_p_data.index

    (p_set_diesel, q_set_diesel) = calculate_diesel_setpoints(load_p_data, load_q_data)

    # AC bus
    # 400V
    network.add("Bus", "AC bus", v_nom=400)

    # Diesel generator
    # Rated capacity 750kVA
    # Minimum load 250kVA
    # Takes over from
    network.add("Generator", "Diesel generator", bus="AC bus", control="PQ", p_set=p_set_diesel, q_set=q_set_diesel)

    # Plant load
    # Modelled as a time varying load
    network.add("Load", "Plant load", bus="AC bus", p_set=load_p_data, q_set=load_q_data)

    # Grid connection
    # Modelled as a slack generator, since feeding back into the grid is not allowed.
    network.add("Generator", "Grid", bus="AC bus", control="Slack")

    return network


def calculate_diesel_setpoints(load_p_data, load_q_data):
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


def calculate_diesel_fuel_usage(p, q):
    """
    Calculate diesel fuel generation based on approximate diesel consumption chart here for a 750kW genset.
    Values inbetween the given points are linearly interpolated.
    https://www.generatorsource.com/Diesel_Fuel_Consumption.aspx

    25% load: 62 l/h
    50% load: 104 l/h
    75% load: 149 l/h
    100% load: 202 l/h

    :param p: active power usage
    :param q: reactive power usage
    :return: diesel usage in liters
    """
    s = p + q
    fuel = 0
    for v in s.values:
        if 0 <= v < 0.25*750:
            fuel += v / (0.25 * 750) * 62
        elif 0.25*750 <= v < 0.5*750:
            fuel += (v - 0.25 * 750) / (0.25 * 750) * (104 - 62) + 62
        elif 0.5 <= v < 0.75*750:
            fuel += (v - 0.5 * 750) / (0.25 * 750) * (149 - 104) + 104
        else:
            fuel += (v - 0.75 * 750) / (0.25 * 750) * (202 - 149) + 149
    return fuel


def calculate_electricity_costs(p, q):
    """
    Calculate electricity costs based on costs per kWh, as well as costs per capacity used and fixed charges

    :param p: active power usage
    :param q: reactive power usage
    :return: calculate energy costs from grid in euros
    """

    cost = 12*(113.275+315.041) # Fixed costs service charge and capacity charge per month

    # Calculate variable cost by active power usage
    for (index, value) in p.items():
        price = get_electricity_price(index)
        cost += value * price

    # Calculate monthly variable capacity costs based on peak kVA and kVAr in each month
    s = p + q
    max_s = s.groupby(s.index.month).max()
    max_q = q.groupby(q.index.month).max()

    for (index, value) in max_s.items():
        cost += value * 14.579
    for (index, value) in max_q.items():
        cost += value * 0.016

    return cost


def get_electricity_price(datetime):
    """
    Get the electricity price per kWh based on the date and time according to the following scheme

    holidays: https://www.gov.za/about-sa/public-holidays

    Summer energy charge (April-September)
    Peak 0.117 €/kWh (0700-1000 and 1800-2000 on weekdays, except public holidays which are: 1/1, 21/3, 29/3, 1/4, 27/4, 1/5, 29/5, 16/6, 17/6, 9/8, 24/9, 16/12, 25/12, 26/12. If a public holiday falls on a sunday, it is the next monday instead.
    Standard 0.088 €/kWh (0600-0700, 1000-1800, 2000-2200 on weekdays, 0700-1200 and 1800-2000 on saturdays and public holidays)
    Off-peak 0.068 €/kWh (1200-0600 on weekdays, 1200-1800 and 2000-0700 on saturdays and public holidays, all day on sundays)

    Winter energy charge (October-March)
    Peak 0.279 €/kWh
    Standard 0.106 €/kWh
    Off-peak 0.073 €/kWh

    :return:
    """
    if 4 <= datetime.month <= 9:
        # Summer
        peak = 0.117
        standard = 0.088
        offpeak = 0.068
    else:
        # Winter
        peak = 0.279
        standard = 0.106
        offpeak = 0.073

    if datetime.dayofweek == 6:
        # Sunday
        price = offpeak
    elif datetime.dayofweek == 5:
        # Saturday
        if 7 <= datetime.hour < 12 or 18 <= datetime.hour < 20:
            price = standard
        else:
            price = offpeak
    elif (datetime.day, datetime.month) in ((1, 1), (21, 3), (29, 3), (1, 4), (27, 4), (1, 5), (29, 5), (16, 6), (17, 6), (9, 8), (24, 9), (16, 12), (25, 12), (26, 12)) or \
          datetime.dayofweek == 0 and ((datetime-pd.Timedelta(1, unit='D')).day, (datetime-pd.Timedelta(1, unit='D')).month) in ((1, 1), (21, 3), (29, 3), (1, 4), (27, 4), (1, 5), (29, 5), (16, 6), (17, 6), (9, 8), (24, 9), (16, 12), (25, 12), (26, 12)):
        # Weekday public holiday
        if 7 <= datetime.hour < 12 or 18 <= datetime.hour < 20:
            price = standard
        else:
            price = offpeak
    else:
        # Weekday
        if 7 <= datetime.hour < 10 or 18 <= datetime.hour < 20:
            price = peak
        elif datetime.hour == 6 or 10 <= datetime.hour < 18 or 20 <= datetime.hour < 21:
            price = standard
        else:
            price = offpeak

    return price


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
    plt.plot(gen_p["Diesel generator"] + gen_q["Diesel generator"], label="Diesel Generator")
    plt.plot(gen_p["Grid"] + gen_q["Grid"], label="Grid")
    plt.plot(load_p + load_q, label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("S [kVA]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Apparent Power")

    print("Energy Consumed from Grid")
    print(f"Active Energy: {gen_p['Grid'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Grid'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['Grid'].sum()/1000+gen_q['Grid'].sum()/1000:.0f} MVAh")
    print(f"Electricity Bill: €{calculate_electricity_costs(gen_p['Grid'], gen_q['Grid']):.0f}\n")

    # https: // www.energy.gov.za / files / esources / petroleum / September2021 / Fuel - Price - History.pdf
    # average fuel cost calculated as:
    print("Energy Consumed from Diesel Generator: ")
    print(f"Active Energy: {gen_p['Diesel generator'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Diesel generator'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {gen_p['Diesel generator'].sum()/1000+gen_q['Diesel generator'].sum()/1000:.0f} MVAh")
    print(f"Fuel Usage: {calculate_diesel_fuel_usage(gen_p['Diesel generator'], gen_q['Diesel generator']):.0f} l")
    print(f"Fuel Cost: €{calculate_diesel_fuel_usage(gen_p['Diesel generator'], gen_q['Diesel generator'])*0.81:.0f}\n")

    print("Energy Consumed by Load: ")
    print(f"Active Energy: {load_p['Plant load'].sum()/1000:.0f} MWh")
    print(f"Reactive Energy: {load_q['Plant load'].sum()/1000:.0f} MVArh")
    print(f"Apparent Energy: {load_p['Plant load'].sum()/1000+load_q['Plant load'].sum()/1000:.0f} MVAh")

    plt.show()

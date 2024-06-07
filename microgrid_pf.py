import pypsa
import math
import pandas as pd
import matplotlib.pyplot as plt
from lib import calculate_electricity_costs, calculate_diesel_fuel_usage, calculate_soc, calc_s

# Parameters
PV_INSTALLED_CAPACITY = 960  # [kiloWatt-peak]
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/
CONVERTER_EFFICIENCY = 0.95  #  efficiency for power converters https://www.edn.com/efficiency-calculations-for-power-converters/ https://www.energysavingtrust.org.uk/sites/default/files/reports/Solar%20inverters.pdf
BATT_EFFICIENCY = 0.9  # 10% lost on charging, 10% on discharging https://www.eia.gov/todayinenergy/detail.php?id=46756
BATT_NOM_ENERGY = 2209  # [kWh] battery energy capacity
# Assume that the battery can be fully charged/discharged in 2 hours
BATT_NOM_POWER = BATT_NOM_ENERGY / 2
BATT_SOC_INITIAL = BATT_NOM_ENERGY/2  # [kWh] initial state of charge assumed to be 50%
GRID_AVAILABLE_HOURS = [1, 2, 3, 4, 5, 10, 11, 12, 13, 17, 18, 19, 20, 21]  # List of hours in which grid is available, example 0 means from 00:00 through 01:00

# to do
# pv data validation
# 2nd control strategy
# simulate random grid failure
# take battery power limit into account


#assumptions
# self discharge rate not taken into account
# ignoring line losses
# balanced system
# taking into account apparent power, assuming that reactive power can be met
# transients not taken into account, high level microgrid dispatch only
# battery power limit constant
# battery power no factor
# constant efficiencies


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


def initialize_network(strategy):
    """
    Set up the pypsa network

    :param strategy: selection of control strategy
    :return: network
    """

    _network = pypsa.Network()

    (load_p_data, load_q_data) = get_load_data()
    pv_data = get_pv_data()

    _network.snapshots = load_p_data.index

    (p_set_diesel, q_set_diesel, p_set_battery, q_set_battery, p_set_pv, q_set_pv) = calculate_setpoints(load_p_data, load_q_data, pv_data, strategy)

    # AC bus
    # 400V
    _network.add("Bus", "AC bus", v_nom=400)

    # PV
    _network.add("Generator", "PV", bus="AC bus",
                control="PQ",
                p_set=p_set_pv,
                q_set=q_set_pv)

    # Battery
    _network.add("StorageUnit", "BESS", bus="AC bus",
                control="PQ",
                p_set=p_set_battery,
                q_set=q_set_battery)

    # Diesel generator
    _network.add("Generator", "Diesel generator", bus="AC bus",
                control="PQ",
                p_set=p_set_diesel,
                q_set=q_set_diesel)

    # Plant load
    # Modelled as a time varying load
    _network.add("Load", "Plant load", bus="AC bus",
                p_set=load_p_data,
                q_set=load_q_data)

    # Grid connection
    # Modelled as a slack generator
    _network.add("Generator", "Grid", bus="AC bus", control="Slack")

    return _network


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
    elif strategy == 'tou':
        return calculate_setpoints_tou(load_p_data, load_q_data, pv_data)
    else:
        raise NotImplemented(f"Strategy {strategy} is not implemented.")


def calculate_setpoints_tou(load_p_data, load_q_data, pv_data):
    """
    Implement time-of-use optimize strategy

    Use as much PV as possible, using the excess to charge the batteries (or curtail if full)

    Prioritize using the battery when prices are high, and grid when prices are low

    So use grid during off-peak hours only,
    use battery during standard and peak hours
    recharge battery during off-peak hours if needed (if battery is under 50% during off-peak)

    Priority 1: PV
    Priority 2: BESS (only if soc > 20%)
    Priority 3: Grid
    Priority 4: BESS (soc <= 20%)
    Priority 5: genset

    """
    # track the battery state of charge in kWh
    _soc = BATT_SOC_INITIAL

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
            if _soc <= BATT_NOM_ENERGY - (s_pv - s_load) * (BATT_EFFICIENCY):
                # pv overproduction used to charge battery if there is space in the battery
                s_batt = -(s_pv - s_load)
            else:
                # pv overproduction wasted by curtailment
                s_pv = s_load
        elif s_pv < s_load:
            # Gap between pv and load is filled based on priority
            if _soc > 0.2*BATT_NOM_ENERGY + (s_load-s_pv) / (BATT_EFFICIENCY):
                # battery can be used while staying above 20% soc
                s_batt = s_load - s_pv
            elif dt.hour not in GRID_AVAILABLE_HOURS:
                # Grid not available, so gap will have to be made up with remaining battery (under 20% soc) + diesel genset
                if _soc >= (s_load-s_pv) / (BATT_EFFICIENCY):
                    # Battery can be used while staying above 0 soc
                    s_batt = s_load - s_pv
                else:
                    # Battery cannot be used while staying above 0 soc. diesel generator kicks in and charges battery with remainder
                    s_diesel = max(250, s_load - s_pv)
                    s_diesel = min(750, s_diesel)
                    if s_diesel > s_load - s_pv:
                        s_batt = s_load - s_pv - s_diesel

        # adjust soc
        if s_batt >= 0:
            _soc -= s_batt / BATT_EFFICIENCY
        else:
            _soc -= s_batt * BATT_EFFICIENCY
        _soc = min(_soc, BATT_NOM_ENERGY)
        _soc = max(0, _soc)

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
    _soc = BATT_SOC_INITIAL

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
            if _soc <= BATT_NOM_ENERGY - (s_pv - s_load) * (BATT_EFFICIENCY):
                # pv overproduction used to charge battery if there is space in the battery
                s_batt = -(s_pv - s_load)
            else:
                # pv overproduction wasted by curtailment
                s_pv = s_load
        elif s_pv < s_load:
            # Gap between pv and load is filled based on priority
            if _soc > 0.2*BATT_NOM_ENERGY + (s_load-s_pv) / (BATT_EFFICIENCY):
                # battery can be used while staying above 20% soc
                s_batt = s_load - s_pv
            elif dt.hour not in GRID_AVAILABLE_HOURS:
                # Grid not available, so gap will have to be made up with remaining battery (under 20% soc) + diesel genset
                if _soc >= (s_load-s_pv) / (BATT_EFFICIENCY):
                    # Battery can be used while staying above 0 soc
                    s_batt = s_load - s_pv
                else:
                    # Battery cannot be used while staying above 0 soc. diesel generator kicks in and charges battery with remainder
                    s_diesel = max(250, s_load - s_pv)
                    s_diesel = min(750, s_diesel)
                    if s_diesel > s_load - s_pv:
                        s_batt = s_load - s_pv - s_diesel

        # adjust soc
        if s_batt >= 0:
            _soc -= s_batt / BATT_EFFICIENCY
        else:
            _soc -= s_batt * BATT_EFFICIENCY
        _soc = min(_soc, BATT_NOM_ENERGY)
        _soc = max(0, _soc)

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


def validate_results(gen_p, gen_q, soc, diesel_usage, store_p, store_q, pv_data):
    """
    Check if the project goals are met:

    90% diesel usage reduction
    100% load met at all times
    soc staying between 0 and 100%
    no feed in to grid
    calculate battery losses and pv curtailed energy

    :return:
    """

    # check soc
    if soc.min() < 0:
        print("SOC goes below 0%!")
    elif soc.max() > 100:
        print("SOC goes above 100%!")
    else:
        print("SOC OK")

    # check diesel usage
    # 318242 l in basecase
    if diesel_usage > 318242*0.1:
        print(f"Diesel usage is HIGHER than target of {318242*0.1} l")
    else:
        print(f"Diesel usage is LOWER than target of {318242 * 0.1} l")

    # check grid feed in, ignore floating point errors
    if gen_p["Grid"].min() < 0 or gen_q["Grid"].min() < 0:
        peak = calc_s(gen_p['Grid'].clip(upper=0).min(), gen_q['Grid'].clip(upper=0).min())
        total = calc_s(gen_p['Grid'].clip(upper=0).sum(), gen_q['Grid'].clip(upper=0).sum())
        if peak > 1e-5 or total > 1e-5:
            print(f"Feed-in to grid detected. Peak: {peak:.1f}kVA. Total: {total:.1f}kVAh.")

    # check load met, ie there should be no supply from grid when grid is unavailable
    peak = 0
    total = 0
    s = calc_s(gen_p["Grid"], gen_q["Grid"])
    for index, value in s.items():
        if index.hour not in GRID_AVAILABLE_HOURS:
            peak = max(peak, s[index])
            total += s[index]
    if peak > 1e-5 or total > 1e-5:
        print(f"Load not met, feed-in from grid during grid unavailability detected. Peak: {peak:.1f}kVA. Total: {total:.1f}kVAh.")

    # Calculate total battery losses
    loss = 0
    s = calc_s(store_p, store_q)
    for index, value in s.items():
        if s[index] < 0:
            loss += abs(s[index] - (s[index] * BATT_EFFICIENCY))
        elif s[index] > 0:
            loss += s[index]/BATT_EFFICIENCY - s[index]
    if loss > 1e-5:
        print(f"Battery losses: {loss/1000.0:.1f}kVAh.")

    # Calculate curtailed PV
    curtailed = 0
    s = calc_s(gen_p["PV"], gen_q["PV"])
    for index, value in s.items():
        if s[index] < pv_data[index]:
            curtailed += pv_data[index] - s[index]
    if curtailed > 1e-5:
        print(f"Curtailed PV: {curtailed/1000.0:.1f}kVAh.")


if __name__ == "__main__":
    network = initialize_network('priority')

    network.pf()

    gen_p = network.generators_t.p
    gen_q = network.generators_t.q

    load_p = network.loads_t.p
    load_q = network.loads_t.q

    store_p = network.storage_units_t.p
    store_q = network.storage_units_t.q

    soc = calculate_soc(store_p, store_q, BATT_NOM_ENERGY, BATT_SOC_INITIAL, BATT_EFFICIENCY)

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
    plt.plot(calc_s(gen_p["Diesel generator"], gen_q["Diesel generator"]), label="Diesel Generator")
    plt.plot(calc_s(gen_p["Grid"], gen_q["Grid"]), label="Grid")
    plt.plot(calc_s(gen_p["PV"], gen_q["PV"]), label="PV")
    plt.plot(calc_s(store_p["BESS"], store_q["BESS"]), label="BESS")
    plt.plot(calc_s(load_p, load_q), label="Load")
    plt.xlabel("Time (hour)")
    plt.ylabel("S [kVA]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("Apparent Power")

    # Plot State of Charge
    plt.figure(3)
    plt.plot(soc, label="BESS")
    plt.xlabel("Time (hour")
    plt.ylabel("State of Charge [%]")
    plt.grid(True)
    plt.legend(loc="best")
    plt.title("State of Charge")

    print("Energy Consumed from Grid")
    print(f"Active Energy: {gen_p['Grid'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Grid'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(gen_p['Grid'].sum() / 1000, gen_q['Grid'].sum() / 1000):.0f} MVAh")
    print(f"Electricity Bill: €{calculate_electricity_costs(gen_p['Grid'], gen_q['Grid']):.0f}\n")

    diesel_usage = calculate_diesel_fuel_usage(calc_s(gen_p['Diesel generator'], gen_q['Diesel generator']))
    print("Energy Consumed from Diesel Generator: ")
    print(f"Active Energy: {gen_p['Diesel generator'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['Diesel generator'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(gen_p['Diesel generator'].sum() / 1000, gen_q['Diesel generator'].sum() / 1000):.0f} MVAh")
    print(f"Fuel Usage: {diesel_usage:.0f} l")
    print(f"Fuel Cost: €{diesel_usage*0.81:.0f}\n")

    print("Energy Consumed from PV: ")
    print(f"Active Energy: {gen_p['PV'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {gen_q['PV'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(gen_p['PV'].sum() / 1000, gen_q['PV'].sum() / 1000):.0f} MVAh\n")

    print("Energy Consumed by Load: ")
    print(f"Active Energy: {load_p['Plant load'].sum() / 1000:.0f} MWh")
    print(f"Reactive Energy: {load_q['Plant load'].sum() / 1000:.0f} MVArh")
    print(f"Apparent Energy: {calc_s(load_p['Plant load'].sum() / 1000, load_q['Plant load'].sum() / 1000):.0f} MVAh\n")

    print(f"Average SOC: {soc.mean():.1f}%\n")

    validate_results(gen_p, gen_q, soc, diesel_usage, store_q, store_q, get_pv_data())

    plt.show()

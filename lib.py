import pandas as pd


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

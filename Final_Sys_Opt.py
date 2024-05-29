import numpy as np
from scipy.optimize import minimize, least_squares, Bounds
import math

# Example load and solar profiles to ensure some usage of the diesel generator
load_profile = np.array([30, 28, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
                           110, 120, 130, 140, 150, 160, 170, 180, 50, 45, 40, 35, 30, 28, 25, 20])
# Solar profile for 1 kWp installed
solar_profile = np.array([0, 0, 0, 0, 0, 0, 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9,
                          0.5, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
grid_schedule = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                          0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1])
converter_efficiency = 0.95
battery_efficiency = 0.9  # 90% for charging and discharging
PV_PRODUCTION_PER_KWP = 1871  # [kWh] per installed kiloWatt-peak, source: https://segensolar.co.za/introduction/


# Function to calculate the Loss of Load Probability and diesel generator hours needed
def objective(x):
    pv_size = x[0]  # installed kWp
    battery_size = x[1]  # kWh
    soc = 0.5 * battery_size  # State of Charge (starts at 50%)
    diesel_needed_hours = 0  # Number of hours diesel generator is needed
    pv_curtail_hours = 0  # Number of hours the pv is curtailed

    for t in range(len(load_profile)):
        # Calculate PV output based on normalised solar profile, pv_size.
        # Capped to load demand (no feed-in)
        energy_pv = min(pv_size * solar_profile[t], load_profile[t])

        if grid_schedule[t] == 0:  # Grid disconnected
            energy_grid = 0
        else:
            energy_grid = max(0, load_profile[t] - energy_pv)

        # battery fills the gap
        energy_battery = load_profile[t] - energy_pv - energy_grid

        # update soc based on energy supplied
        if energy_battery >= 0:
            soc -= energy_battery / battery_efficiency
        else:
            soc -= energy_battery * battery_efficiency

        # cap soc, if soc is higher than pv should be curtailed
        if soc > battery_size:
            pv_curtail_hours += 1
        soc = min(soc, battery_size)

        # cap soc, if soc got below 0 it means the diesel generator is needed to fill the gap
        if soc < 0:
            diesel_needed_hours += 1

        soc = max(soc, 0)

    output = math.sqrt(diesel_needed_hours**2 + pv_curtail_hours**2)

    return output


# Detailed debugging to check if optimizer changes the values
def debug_optimizer(result, initial_guess):
    print("Optimization Result:")
    print(f"Success: {result.success}")
    print(f"Status: {result.status}")
    print(f"Message: {result.message}")
    print(f"Initial Guess: {initial_guess}")
    print(f"Optimal PV size: {result.x[0]}")
    print(f"Optimal Battery size: {result.x[1]}")
    print(f"Objective value: {result.fun}")


def optimize(initial_guess):
    # Define bounds for PV size and battery size
    bounds = [[0, 0], [np.inf, np.inf]]  # PV size and Battery size must be non-negative

    # Use the minimize function to find the optimal sizes
    result = least_squares(objective, initial_guess, bounds=bounds, method='trf', diff_step=10)

    # Debug output to ensure optimizer worked correctly
    debug_optimizer(result, initial_guess)


if __name__ == "__main__":
    optimize([100, 100])
    optimize([50, 10])
    optimize([500, 100])
    optimize([1000, 200])

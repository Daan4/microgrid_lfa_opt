import numpy as np
from scipy.optimize import minimize

# Example load and solar profiles to ensure some usage of the diesel generator
load_profile = np.array([30, 28, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
                         110, 120, 130, 140, 150, 160, 170, 180, 50, 45, 40, 35, 30, 28, 25, 20])
solar_profile = np.array([0, 0, 0, 0, 0, 0, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90,
                          50, 40, 30, 20, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
grid_schedule = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                          0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1])
battery_efficiency = 0.95


# Function to calculate the Loss of Load Probability and diesel generator hours needed
def objective(x):
    pv_size = x[0]
    battery_size = x[1]
    soc = 0  # State of Charge (initially empty)
    loss_of_load_hours = 0  # Number of hours when the load is not met
    diesel_needed_hours = 0  # Number of hours diesel generator is needed
    
    for t in range(len(load_profile)):
        if grid_schedule[t] == 0:  # Grid disconnected
            energy_from_grid = 0
        else:
            energy_from_grid = max(0, load_profile[t] - pv_size * solar_profile[t])
        
        energy_from_pv = min(pv_size * solar_profile[t], load_profile[t])
        energy_from_battery = min(battery_size, load_profile[t] - energy_from_pv - energy_from_grid)
        soc -= energy_from_battery / battery_efficiency
        soc += pv_size * solar_profile[t] - (load_profile[t] - energy_from_battery - energy_from_grid)
        soc = min(soc, battery_size)
        soc = max(soc, 0)
        
        energy_needed = load_profile[t] - energy_from_pv - energy_from_battery - energy_from_grid
        if energy_needed > 0:
            loss_of_load_hours += 1
            diesel_needed_hours += 1

    return loss_of_load_hours / len(load_profile), diesel_needed_hours

def optimization_function(x):
    return objective(x)[0]

# Define bounds for PV size and battery size
bounds = [(0, None), (0, None)]  # PV size and Battery size must be non-negative

# Initial guess for the optimizer (kw, kwH)
initial_guess = [200, 50]  # Example values

# Detailed debugging to check if optimizer changes the values
def debug_optimizer(result):
    print("Optimization Result:")
    print(f"Success: {result.success}")
    print(f"Status: {result.status}")
    print(f"Message: {result.message}")
    print(f"Initial Guess: {initial_guess}")
    print(f"Optimal PV size: {result.x[0]}")
    print(f"Optimal Battery size: {result.x[1]}")
    print(f"Loss of Load Probability: {result.fun}")

# Use the minimize function to find the optimal sizes
result = minimize(optimization_function, initial_guess, bounds=bounds, method='SLSQP')

# Extract results from the optimization
optimal_pv_size = result.x[0]
optimal_battery_size = result.x[1]
optimized_LOLP = result.fun

# Recalculate the hours diesel generator is needed for the optimal solution
_, diesel_needed_hours = objective(result.x)

# Debug output to ensure optimizer worked correctly
debug_optimizer(result)

print('Hours Diesel Generator Needed:', diesel_needed_hours)

# Verify if optimizer is actually searching for optimal values
def test_with_different_initial_guess(initial_guess):
    result = minimize(optimization_function, initial_guess, bounds=bounds, method='SLSQP')
    _, diesel_needed_hours = objective(result.x)
    
    debug_optimizer(result)
    print('Hours Diesel Generator Needed:', diesel_needed_hours)

# Test with different initial guesses
test_with_different_initial_guess([50, 10])
test_with_different_initial_guess([500, 100])
test_with_different_initial_guess([1000, 200])

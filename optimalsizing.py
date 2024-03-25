import pypsa
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

index = pd.date_range("2024-01-01 00:00", "2024-01-01 23:00", freq="h")

bev_usage = pd.Series([0.0] * 7 + [9.0] * 2 + [0.0] * 8 + [9.0] * 2 + [0.0] * 5, index)

pv_pu = pd.Series([0.0] * 7 + [0.2, 0.4, 0.6, 0.75, 0.85, 0.9, 0.85, 0.75, 0.6, 0.4, 0.2, 0.1] + [0.0] * 5, index)

charger_p_max_pu = pd.Series(0, index=index)
charger_p_max_pu["2024-01-01 09:00":"2024-01-01 16:00"] = 1.0

# df = pd.concat({"BEV": bev_usage, "PV": pv_pu, "Charger": charger_p_max_pu}, axis=1)
# df.plot.area(subplots=True, figsize=(10, 7))
# plt.tight_layout()
# plt.show()

network = pypsa.Network()
network.set_snapshots(index)

network.add("Bus", "place of work", carrier="AC")
network.add("Bus", "battery", carrier="Li-ion")

network.add("Generator", "PV panel", bus="place of work", p_nom_extendable=True, p_max_pu=pv_pu, capital_cost=1000.0)

network.add("Load", "driving", bus="battery", p_set=bev_usage)

network.add("Store", "battery storage", bus="battery", e_cyclic=True, e_nom=100)

network.add("Link", "charger", bus0="place of work", bus1="battery", p_nom=120, p_max_pu=charger_p_max_pu, efficiency=0.9)

network.optimize()

P_pv_optimal = network.generators.p_nom_opt["PV panel"]
losses = network.generators_t.p.loc[:, "PV panel"].sum() - network.loads_t.p.loc[:, "driving"].sum()

P_pv = network.generators_t.p
P_charger = network.links_t.p0
P_batt = network.stores_t.p
E_batt = network.stores_t.e
SOC = E_batt/100

fig, axs = plt.subplots(4, 1, layout="constrained")

t = pd.DataFrame(np.arange(0, 24, 1))

axs[0].plot(t, P_pv, label="P_pv")
axs[0].set_xlabel('Time (hour)')
axs[0].set_ylabel('P_pv [kW]')
axs[0].legend(loc='best')
axs[0].grid(True)

axs[1].plot(t, P_batt, label="P_batt")
axs[1].set_xlabel('Time (hour)')
axs[1].set_ylabel('P_batt [kW]')
axs[1].legend(loc='center')
axs[1].grid(True)

axs[2].plot(t, SOC, label="SOC")
axs[2].set_xlabel('Time (hour)')
axs[2].set_ylabel('SOC')
axs[2].legend(loc='best')
axs[2].grid(True)

axs[3].plot(t, P_charger, label="P_charger")
axs[3].set_xlabel('Time (hour)')
axs[3].set_ylabel('P_charger')
axs[3].legend(loc='best')
axs[3].grid(True)

plt.show()
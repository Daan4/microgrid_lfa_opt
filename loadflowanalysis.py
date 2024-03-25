import pypsa
import numpy as np

network = pypsa.Network()

network.add("Bus", "Bus 0", v_nom=20)
network.add("Bus", "Bus 1", v_nom=20)
network.add("Bus", "Bus 2", v_nom=20)

network.add("Line", "Line 0", bus0="Bus 0", bus1="Bus 1", x=0.1, r=0.01)
network.add("Line", "Line 1", bus0="Bus 1", bus1="Bus 2", x=0.1, r=0.01)
network.add("Line", "Line 2", bus0="Bus 2", bus1="Bus 0", x=0.1, r=0.01)

network.add("Generator", "Gen 0", bus="Bus 0", p_set=100, control="PQ")

network.add("Load", "Load 0", bus="Bus 1", p_set=100, q_set=-100)

network.pf()

gen_p = network.generators_t.p
gen_q = network.generators_t.q

lines_p = network.lines_t.p0
lines_q = network.lines_t.q0

bus_vmag = network.buses_t.v_mag_pu
bus_vang = network.buses_t.v_ang * 180 / np.pi

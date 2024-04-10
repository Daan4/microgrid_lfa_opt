import pypsa
import numpy as np

network = pypsa.Network()

network.add("Bus", "1", v_nom=1)
network.add("Bus", "2", v_nom=1)

network.add("Line", "Line", bus0="1", bus1="2", x=0.1, r=0)

network.add("Generator", "G1", bus="1", control="Slack")

network.add("Load", "L1", bus="2", p_set=-0.5, q_set=-0.5)

network.pf()

gen_p = network.generators_t.p
gen_q = network.generators_t.q

lines_p = network.lines_t.p0
lines_q = network.lines_t.q0

bus_vmag = network.buses_t.v_mag_pu
bus_vang = network.buses_t.v_ang * 180 / np.pi

load_p = network.loads_t.p
load_q = network.loads_t.q

pass
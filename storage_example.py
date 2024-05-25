import pypsa

network = pypsa.examples.storage_hvdc(True, True)

network.opf()

pass
"""Popisy diagnostiky automobilního C++ regulátoru pro telemetrii a GUI."""

STATES = {
    0: "JÍZDA",
    1: "VOLNOBĚH",
    2: "BRZDĚNÍ MOTOREM",
    3: "OMEZOVAČ",
    4: "OCHRANNÉ VYPNUTÍ",
    5: "NOUZOVÝ REŽIM",
}
FAULTS = {
    1: "neplatný nebo starý senzorový snímek",
    2: "CAN timeout",
    4: "nízký tlak oleje",
    8: "teplotní ochrana",
    16: "nízké napětí",
    32: "MAF nahrazen výpočtem MAP/IAT",
    64: "omezení prokluzu",
    128: "nesouhlas podvozkových snímačů",
    256: "prázdná nádrž",
    512: "nízký tlak paliva",
}


def fault_names(mask):
    return [text for bit, text in FAULTS.items() if mask & bit]

# Wokwi části ECU simulátoru

Nové zadání virtuálního hardware implementuje samostatný projekt
**[hardware/README.md](hardware/README.md)** s výchozí ESP32 ECU, odděleným
UART adaptérem v Custom Chipu, konfigurovatelnými snímači a buffered režimem.

Současné `src/main.cpp`, `engine-signals.chip.c` a kořenový `wokwi.toml`
jsou **historické Mega demo** z předchozí fáze. Obsahují simulační protokol
v MCU a nesplňují novou podmínku izolace produkčního ECU firmware.
Zůstávají pro kompatibilitu a staré testy. Pro nové zadání vybírejte
`hardware/wokwi.toml`, nikoli tento historický kořenový konfigurační soubor.

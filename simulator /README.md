# ECU Engine Simulation Starter

A minimal Python engine simulation in a dedicated thread, plus a serial JSON bridge to a simulated ECU in Wokwi for VS Code.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python main.py --mode mock --duration 10
```

For Wokwi: merge `wokwi.toml.example` into the **existing** `wokwi.toml` of your firmware project (retain its firmware and ELF settings), start the Wokwi VS Code simulation, then:

```bash
python main.py --mode wokwi --url rfc2217://localhost:4000 --duration 30
```

## Protocol (JSON Lines over UART)

Host to MCU at 20 Hz:

```json
{"type":"sensors","time_s":1.0,"rpm":1200,"throttle":0.35,"map_kpa":51.25,"coolant_c":85,"crank_deg":120,"lambda_value":1.0}
```

MCU to host (whenever actuator values change):

```json
{"type":"actuators","injector_ms":3.2,"ignition_deg":15,"load_nm":12}
```

The ECU firmware must implement newline-delimited JSON on its UART. The bridge does **not** control MCU GPIO directly. CKP/CMP pulses and microsecond-level injection/ignition timing are **not** simulated at pin level in this version; they require a custom Wokwi chip or another synchronized timing bridge.

## Design constraints

- The engine runs in a Python thread at nominal 10 ms intervals; the bridge runs in the main thread, with a dedicated serial reader thread.
- Shared engine state is guarded by a lock. The Python thread uses wall-clock pacing, not deterministic virtual time.
- Engine dynamics are a toy model, not a calibrated combustion model. It can be used for architecture and protocol experiments, not ECU validation or safety-critical tests.
- RFC2217 is the documented serial forwarding mechanism for Wokwi VS Code. The separate `wokwi-client` Python SDK targets the Wokwi Simulation API and is not used here.
- If Wokwi's simulator tab is hidden, its simulation may pause; serial timing can diverge from host time.

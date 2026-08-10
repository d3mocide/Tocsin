"""Meshtastic egress (design doc §7).

`meshtastic_node.py` rather than the design doc's `meshtastic_serial.py`:
§7's flow is "sendText(wantAck=True) over serial/TCP", and both transports
share one client, so naming the module after just one of them would be
the misleading half of the spec."""

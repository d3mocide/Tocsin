"""Meshtastic dual-path egress (design doc §7, §9's suggested
`egress/{meshtastic_serial,meshtastic_mqtt,mqtt}.py` layout -- introduced
now that there are two real egress mechanisms to group, not before).

`meshtastic_node.py` rather than the design doc's `meshtastic_serial.py`:
§7's flow is "sendText(wantAck=True) over serial/TCP", and both transports
share one client, so naming the module after just one of them would be
the misleading half of the spec."""

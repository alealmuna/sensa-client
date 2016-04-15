# Sensa python client

Client that provides communication between the data accessed by the
microcontroller and the web service to storage, visualize and control.

The Sensa serial protocol is used to communicate with the
microcontroller through the serial port.

The client starts by reading the config file, activating the stored IOs
on the microcontroller and then checking for internet connection.

A connection is established with the socket server for listening to
changes on subscribed datastreams and also instructions from the
server.  The data starts being sampled and posted to the
server according to the sampling_period variable and the activated
datastreams defined on the config file.

## Socket server command messages
Activate IO

: ```{"action": "activateIO", "type": "<IO_TYPE>", "pin":"<pin_ID>"}```

Install new firmware

: ```{"action": "install_fw", "version":"<firmware_version>"}```

Updated value from subscribed device

: ```{"id": "<datastream_id>", "value": "<new_value>"}```

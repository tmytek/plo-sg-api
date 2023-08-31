# plo-sg-api

## Requirments
1. Python >= 3.8
2. pyserial packege
3. For windows user CP2102 driver (https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers?tab=downloads)

## Usage
Use `--help` to show help message.

```
python .\plo_sg_api.py --help
```
```
usage: plo_sg_api.py [-h] [--scan] [--com COM] [--set_freq SET_FREQ] [--n N] [--get_n_freq GET_N_FREQ] [--freq_count] [--id] [--hw_ver] [--fw_ver] [--post_multi] [--set_ref SET_REF] [--sn] [--plo_sn] [--dip_sw]

optional arguments:
  -h, --help            show this help message and exit
  --scan                Scan SG device and list info
  --com COM             com port. If not specified will connect to first SG in scan list
  --set_freq SET_FREQ   Set output frequency (kHz). Use --n to saved to eeprom
  --n N                 Nth saved frequency. Used with --set_freq
  --get_n_freq GET_N_FREQ
                        Get Nth saved frequency (kHz)
  --freq_count          Get number of available saved frequency
  --id                  Get PLO module id
  --hw_ver              Get PLO module hw version
  --fw_ver              Get PLO module fw version
  --post_multi          Get PLO output post multiplication. X1, X2 or X4
  --set_ref SET_REF     Set reference clock frequency (kHz)
  --sn                  Get SG sn
  --plo_sn              Get PLO module internal sn
  --dip_sw              Get dip switch reading
```

## Example
* Scan PLO-SG device
```
python .\plo_sg_api.py --scan
```
* Connect to PLO-SG device.
    * Use `--com` to connect to PLO-SG on specific com port.
    ```
    python .\plo_sg_api.py --com COM8
    ```
    * If no com port is provided then the api will connect to the first device in the scan list.

* Set output frequency to 6GHz.
```
python .\plo_sg_api.py --set_freq 6000000
```
* Set output frequency to 6GHz to the PLO-SG on com8 .
```
python .\plo_sg_api.py --com COM8 --set_freq 6000000
```
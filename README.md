### ya-perf

Performance analyzing tool for NET

### Available tests

* **GFTP transfer test** between Requestor and each Provider. Only one transfer at a time between Requestor and Provider.

| Command line option  | Default | Description                            |
|----------------------|---------|----------------------------------------|
| --transfer           | false   | Option to enable test                  |
| --transfer-file-size | 10      | Sets transferred file size (in Mbytes) |

WARNING: Be aware that large size of transferred files increase total test time.

* **VPN ping test** between Providers. Only one ping test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of ping test: _n(n-1)_ where _n_ is number of instances). In example the VPN ping test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B).

| Command line option | Default | Description                                   |
|---------------------|---------|-----------------------------------------------|
| --vpn-ping          | false   | Option to enable test                         |
| --ping-count        | 10      | Specifies the number of ping packets to send. |

* **VPN transfer test** between Providers. Only one transfer test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of transfer test: _n(n-1)_ where _n_ is number of instances). In example the VPN transfer test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B). In the background script uses `iperf 3.11` as a performance testing tool. Bandwidth is measured on TCP protocol.
TCP window size is set to 60000 bytes.

| Command line option | Default | Description           |
|---------------------|---------|-----------------------|
| --vpn-transfer      | false   | Option to enable test |

### General options

| Command line option          | Default     | Description                                                                    |
|------------------------------|-------------|--------------------------------------------------------------------------------|
| --num-instances              | 2           | Number of provider nodes to be tested                                          |
| --subnet-tag                 | devnet-beta | Set subnet name                                                                |
| --payment-driver, --driver   | erc20       | Set payment network driver                                                     |
| --payment-network, --network | rinkeby     | Set payment network name                                                       |
| --json                       | false       | Save results in JSON format                                                    |
| --log-file                   | ya-perf     | Log file for YAPAPI                                                            |
| --running-time               | 1200        | Option to set time the instance run before the cluster is stopped (in seconds) |

### Example

```bash
python3 performance.py --num-instances 2 --subnet-tag testnet --transfer true --transfer-file-size 25 --vpn-ping true --ping-count 5 --vpn-transfer true --json true
```

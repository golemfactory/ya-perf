# ya-perf

Performance analyzing tool for NET

### Available tests

* **GFTP transfer test** between Requestor and each Provider. Only one transfer at a time between Requestor and Provider.

| Command line option  | Default  | Description                            |
|----------------------|----------|----------------------------------------|
| --transfer           | disabled | Optional flag to enable test           |
| --transfer-file-size | 10       | Sets transferred file size (in Mbytes) |

WARNING: Be aware that large size of transferred files increase total test time.

* **VPN ping test** between Providers. Only one ping test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of ping test: _n(n-1)_ where _n_ is number of instances). In example the VPN ping test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B).

| Command line option | Default  | Description                                   |
|---------------------|----------|-----------------------------------------------|
| --vpn-ping          | disabled | Optional flag to enable test                  |
| --ping-count        | 10       | Specifies the number of ping packets to send. |

* **VPN transfer test** between Providers. Only one transfer test at a time between Providers. Each Provider is engaged in only one call at a time, as a client or a server.
Test is only completed when each Provider call others (total number of transfer test: _n(n-1)_ where _n_ is number of instances). In example the VPN transfer test is completed when 
3 nodes (A,B,C) complete 6 tests (A->B, B->A, A->C, C->A, B->C, C->B). In the background script uses `iperf 3.11` as a performance testing tool. Bandwidth is measured on TCP protocol.
TCP window size is set to 60000 bytes.

| Command line option | Default  | Description                  |
|---------------------|----------|------------------------------|
| --vpn-transfer      | disabled | Optional flag to enable test |

### General options

| Command line option          | Default     | Description                                                                    |
|------------------------------|-------------|--------------------------------------------------------------------------------|
| --num-instances              | 2           | Number of provider nodes to be tested                                          |
| --subnet-tag                 | devnet-beta | Set subnet name                                                                |
| --payment-driver, --driver   | erc20       | Set payment network driver                                                     |
| --payment-network, --network | rinkeby     | Set payment network name                                                       |
| --json                       | disabled    | Set the flag and save results in JSON format                                   |
| --log-file                   | ya-perf     | Log file for YAPAPI                                                            |
| --running-time               | 1200        | Option to set time the instance run before the cluster is stopped (in seconds) |

### Filtering nodes
You can use any Providers in the subnet (by default) or specify nodes to test. If order to filter nodes, enter Provider ID in `providers_list.json` file,
i.e.
```json
[
  "0x83a086e7779c31476eefee36ab8814bca3d35aa2",
  "0xd2ca30dff73047cb3619416b9de187686c31c6f6",
  "0xb7925f9378650e7291836ef9249e2fcdf8a378da",
  "0x02a71376b982cb3752e99252625aa4cc33b7ed3d",
  "0x0d6beaeec5e3a250ef909ffad58271780a340fea",
  "0xdf4b685011fb4b061e6ecb1f418d44e6cb3504d6"
]
```
Providers are selected for the test according to the order given in the file.

### Example

```bash
python3 performance.py --num-instances 2 --subnet-tag testnet --transfer --transfer-file-size 25 --vpn-ping --ping-count 5 --vpn-transfer --json
```

# GSB perf

Measuring local GSB performance. File is published and downloaded on the same machine.

`poetry run python3 gsb-perf.py --transfer-file-size 100`

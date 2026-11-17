# Test case: virtual LAN client + continuous traffic (OPNsense / FreeBSD)

**Status:** executed 2026-11-16/17 on opnvm1 (OPNsense 26.7, FreeBSD 15.1) — PASS.
**Runtime:** ~30 min live, controller showed WAN throughput + client row.

## Purpose

Give the emulated gateway a **real LAN client with real routed traffic** when no
physical client VM is available, so the UniFi controller shows:

* WAN/LAN interface counters and throughput moving (from live `ifstat`),
* a client row (from the KEA lease file → `ipv4_active_leases` in the inform).

Everything is **runtime-only** (jail/bridge/epair/sysctls/lease row) — a reboot
returns the box to its prior state. Nothing is written to `config.xml`.

## Topology

```
 jail "vclient" (VIMAGE, own stack)          host (opnvm1)
 ┌──────────────────┐   epair0b ── epair0a ┌─────────────────────────────┐
 │ 192.168.1.50/24  │═══════════╗          │ bridge0 ── vtnet1 (LAN)     │
 │ MAC 58:9c:fc:…3b │          ╚══════════►│ 192.168.1.1 → route/NAT →   │
 └──────────────────┘          bridge      │ vtnet0 (WAN) → upstream     │
 └─────────────────────────────────────────┘
```

The jail owns the client address, so the host treats its traffic exactly like a
foreign LAN client (routes + NATs it, learns its ARP **on vtnet1**).

## Setup

```sh
# 1. virtual wire
EP=$(ifconfig epair create)          # -> epair0a (b-end: epair0b)
BR=$(ifconfig bridge create)         # -> bridge0
ifconfig $BR addm vtnet1 addm ${EP%a}a up

# 2. jail client
jail -c name=vclient path=/ host.hostname=vclient vnet persist
ifconfig ${EP%a}b vnet vclient
jexec vclient ifconfig ${EP%a}b inet 192.168.1.50/24 up
jexec vclient ifconfig lo0 inet 127.0.0.1 up
jexec vclient route add default 192.168.1.1

# 3. REQUIRED workaround — pin the gateway MAC in the jail (gotcha G1)
LANMAC=$(ifconfig vtnet1 | awk '/ether/{print $2}')
jexec vclient arp -s 192.168.1.1 $LANMAC

# 4. register the client where the emulator looks (gotcha G3)
EXP=$(($(date +%s) + 604800))
echo "192.168.1.50,$(jexec vclient ifconfig ${EP%a}b | awk '/ether/{print $2}'),,7200,$EXP,1,0,0,vclient,0,," \
  >> /var/db/kea/kea-leases4.csv
```

Use an address **outside** the KEA pool (pool is .100–.250, client takes .50).

### Traffic loop (run inside the jail)

`/root/vclient-traffic.py` — internal bulk pull + periodic external fetch + DNS
through the gateway. `fetch(1) -H` is broken on FreeBSD 15 ("implicit headers"),
so use python `urllib`:

```python
import time, urllib.request, subprocess
TOKEN = open('/root/ak-token').read().strip()
AK = 'http://<ak-host>:8082/general/<repo>/FreeBSD:15:amd64/<big-file>.pkg'
i = 0
while True:
    i += 1
    try:
        req = urllib.request.Request(AK, headers={'Authorization': 'Bearer ' + TOKEN})
        print(len(urllib.request.urlopen(req, timeout=30).read()), flush=True)
    except Exception as e:
        print('error:', e, flush=True); time.sleep(5)
    if i % 10 == 0:
        try: urllib.request.urlopen('https://pkg.opnsense.org/FreeBSD:15:amd64/26.7/latest/packagesite.pkg', timeout=15).read()
        except Exception: pass
        for d in ('google.com', 'github.com'):
            subprocess.run(['drill', '@192.168.1.1', d, 'A'], capture_output=True)
    time.sleep(2)
```

```sh
jexec vclient daemon -p /var/run/vclient-traffic.pid -o /var/log/vclient-traffic.log \
  python3 /root/vclient-traffic.py
```

~10 MB every ~3 s ≈ 28 Mbps sustained. Store any token as `/root/ak-token` mode
600 and **delete it at teardown**.

## Gotchas (all three cost real debugging time)

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| G1 | Jail can ARP the gateway but routed traffic dies; host never forwards | FreeBSD **weak-host ARP**: the host answers the jail's ARP request (delivered via epair0a) with **epair0a's MAC**, not vtnet1's. Frames then enter the stack on epair0a, where pf's anti-spoof (`block on !vtnet1 from 192.168.1.0/24`) and default-deny kill them. | Pin a **static ARP** in the jail for the gateway IP → vtnet1's MAC. Frames then bridge-forward to vtnet1, enter the stack on vtnet1, pass pf. |
| G2 | `dhclient` in the jail never gets an OFFER; broadcast doesn't even reach vtnet1 | **Bridge members stuck in RSTP `DISCOVER`** (learning, never forwarding) — broadcast flood to vtnet1 is dropped at the bridge layer. Unicast to a learned MAC still works (local delivery), which masks this for ICMP. `-stp` on members did not clear it. | Don't rely on DHCP from a jailed client on this kernel; register the lease directly (G3). Real NICs / real client VMs are unaffected. |
| G3 | Client passes traffic but never appears in the controller | The emulator's client list comes **only from the KEA lease file** (`dhcp_leases` → `ipv4_active_leases`), not from the ARP table. | Append a lease CSV row for the client's MAC/IP/hostname (outside the pool). KEA (memfile) only rewrites the file on lease events — with no other clients the row persists until KEA restarts or a real client gets a lease. |

Also: `net.link.bridge.pfil_member=1` (OPNsense sets it) makes pf filter
bridge-member ingress — relevant while debugging G1/G2; leave it as found (1).

## Verify

```sh
# client visible to the host on the LAN interface
arp -an | grep 192.168.1.50          # expect: on vtnet1

# traffic flowing (10 MB pulls in the log, WAN counters rising)
tail /var/log/vclient-traffic.log
netstat -ibn -I vtnet0

# the emulator will report the client in its next inform
cd /opt/unifi-gateway && venv/bin/python - <<'PY'
import configparser, json
from collectors import create_collector
cp = configparser.RawConfigParser(); cp.read('/usr/local/etc/unifi-gateway/unifi-gateway.conf')
print(json.dumps(create_collector(cp).data['dhcp_leases']))
PY
```

Expected: the lease JSON contains the client; the controller UI shows the
gateway's WAN sparkline moving and a `vclient` row under Clients.
(DPI stub rows are static — they don't change with real traffic.)

## Teardown

```sh
kill $(cat /var/run/vclient-traffic.pid)
jail -r vclient
ifconfig epair0a destroy          # destroys both ends
ifconfig bridge0 destroy
sed -i '' '/^192\.168\.1\.50,/d' /var/db/kea/kea-leases4.csv
arp -d 192.168.1.50 2>/dev/null
rm -f /root/ak-token /root/vclient-traffic.py /var/log/vclient-traffic.log \
      /var/run/vclient-traffic.pid
```

Verify: `jls` empty, no `epair`/`bridge` in `ifconfig -l`, lease row gone,
`sysctl net.link.bridge.pfil_member` = 1, packaged daemon still `noop`s.

## Notes / real trafgen

* The real trafgen VM is `192.168.1.191` (behind opnvm1 LAN), SSH via
  `user@` with `/tmp/trafgen_key` on opnvm1 — **that key is currently missing
  and must be re-authorized** (noted 2026-11-02). Once it's powered on and
  reachable, prefer it over this simulation: it gets a real KEA lease from the
  pool (.100–.250) and needs no workarounds.
* This simulation is a stand-in for controller-visibility testing only; it is
  not a performance or DPI-fidelity test.

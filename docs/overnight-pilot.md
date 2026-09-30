# Overnight operation

The controller admits normal runs between 10 PM and 6 AM America/New_York. A supervised `--pilot` run can operate outside that window. An approved packet limits a run to two workers, one repair per worker, and 60 minutes. Failed runs remain inspectable. A successful run publishes a draft PR; a human reviews and merges it.

`controller/overnight.py` and the service template support a bounded scheduled run. Configure your own packet and host paths before installing the service. Scheduling is implemented; unattended reliability remains unproven. Reboot, Docker runtime selection, and changed host addresses require operator attention in this alpha.

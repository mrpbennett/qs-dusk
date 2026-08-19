[Unit]
Description=Dusk — automatic Omarchy theme switching (solar or scheduled)
Documentation=file:__DUSK_HOME__/docs/usage.md
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=__PYTHON__ __DUSK_HOME__/bin/dusk-scheduler
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/share/omarchy/bin
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
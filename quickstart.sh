#!/bin/sh
opkg update
opkg install distribute
opkg install python-openssl
opkg install python-doc
easy_install pip
pip install pyserial
pip install requests
opkg install python-sqlite3
opkg install sqlite3-cli
opkg install screen
opkg install bc

# Disable login on ttyATH0 by
sed -i 's/ttyATH0/#ttyATH0/' /etc/inittab
echo "Reboot MCU when rebooting linux"
echo "reset-mcu
/sbin/reboot" >> /bin/reboot
sed -i 's/#reset/reset/' /etc/rc.local
# Disable wifi restart on rc.local
sed -i 's/wifi/#\ wifi/' /etc/rc.local
sed s/sbin\\/reboot/bin\\/reboot/g /usr/bin/wifi-reset-and-reboot
chmod +x /bin/reboot

uci del system.@system[0].timezone_desc
uci del system.@system[0].zonename
uci set system.@system[0].timezone=GMT3
uci delete system.ntp.server
uci add_list system.ntp.server='ntp.shoa.cl'
uci add_list system.ntp.server='0.cl.pool.ntp.org'
uci add_list system.ntp.server='0.south-america.pool.ntp.org'
uci add_list system.ntp.server='3.south-america.pool.ntp.org'
uci commit system;
uci set dropbear.@dropbear[0].Port=2222
uci commit dropbear
/etc/init.d/dropbear restart
opkg update
opkg install openssh-server
/etc/init.d/sshd enable
/etc/init.d/sshd start
/etc/init.d/dropbear disable
/etc/init.d/dropbear stop
echo "* * * * * /usr/bin/sensa_watchdog.sh" | crontab -
mkdir /root/log
mkdir /mnt/sd/db

mv sensa_rsa.pub /etc/dropbear/authorized_keys
mv sensa /etc/init.d/
mv sensa_watchdog.sh /usr/bin
mv sensa.py /usr/bin
mv sensa.ini /etc/

# echo "Setting up hostname and timezone"
# device_id=$(awk -F "= " '/device_id/ {print $2}' sensa.ini)
# uci set system.@system[0].hostname=sensa$device_id
# echo "Changing root password"
# passwd << EOF
# sensa-$device_id
# sensa-$device_id
# EOF
# rm $0
#
rm /root/quickstart.sh
reboot

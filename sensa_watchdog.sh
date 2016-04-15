   #!/bin/sh

# Record the last time it associates to the AP
ASSOC_FILE=/tmp/last_assoc.wlan0
if [ -e $ASSOC_FILE ]; then
    LAST_LOG=$(cat $ASSOC_FILE)
fi

LAST_ASSOC=$(dmesg | grep 'wlan0: associated' | tail -1 | tr -d '[]' | awk {'print $1'})

echo "Last log : " $LAST_LOG
echo "Last assoc: " $LAST_ASSOC

if [ -z $LAST_LOG ]; then
    echo $LAST_ASSOC > $ASSOC_FILE
elif [ $(echo "$LAST_ASSOC > $LAST_LOG" | bc) -eq "1" ]; then
    # Reconnection detected, restart client
    echo $LAST_ASSOC > $ASSOC_FILE
    /etc/init.d/sensa restart
fi

if [ ! -f /var/run/sensa.pid ]; then
    printf "Sensa PID not found. Restarting client."
    /etc/init.d/sensa start
fi
# Stores the cumulative (dis)connected times by day
CONNECTION_FILE=/root/log/conn_times.log
TODAY=$(date +"%Y%m%d")

if [ -e $CONNECTION_FILE ]; then
    LAST_LOG=$(tail -1 $CONNECTION_FILE)
    LAST_LOG_DATE=$(echo $LAST_LOG | awk {'print $1'})
    if [ $LAST_LOG_DATE -ne $TODAY ]; then
        echo $TODAY "0 0" >> $CONNECTION_FILE
        echo "New day to log connection times"
        exit
    fi
    CONNECTED_TIME=$(echo $LAST_LOG | awk {'print $2'})
    DISCONNECTED_TIME=$(echo $LAST_LOG | awk {'print $3'})
else
    echo $TODAY "0 0" > $CONNECTION_FILE
    echo "Time log file created"
    exit
fi

echo "Connected time: " $CONNECTED_TIME
echo "Disconnected time: " $DISCONNECTED_TIME

DEVICE_ID=$(grep device_id /etc/sensa.ini | awk {'print $3'})
API_TOKEN=$(grep api_token /etc/sensa.ini | awk {'print $3'})
API_URL=$(grep api_url /etc/sensa.ini | awk {'print $3'})
DEVICE_URL=$API_URL/devices/$DEVICE_ID
# Check connection to internet
wget -q --tries=3 --timeout=10 --spider http://google.com
if [[ $? -ne 0 ]]; then
    DISCONNECTED_TIME=$(($DISCONNECTED_TIME + 1))
    sed -i '$ s/[^ ]*[^ ]/'$DISCONNECTED_TIME'/3' $CONNECTION_FILE
    # Restart network and client
    echo "Disconnected from internet. Restarting network and client"
    /etc/init.d/network restart
    /etc/init.d/sensa restart
else
    echo "Connection available."
    CONNECTED_TIME=$(($CONNECTED_TIME + 1))
    sed -i '$ s/[^ ]*[^ ]/'$CONNECTED_TIME'/2' $CONNECTION_FILE
    DEVICE=$(curl -H "Authorization: Token token=$API_TOKEN" $DEVICE_URL)
    STATUS=$(echo $DEVICE | awk -Fstatus\": '{print substr($2, $0, 1)}')
    if [[ ${STATUS} -eq  0 ]]; then
        # Connection available but status disconnected on server. Restart client
        echo "Socket disconnected. Restarting client"
        /etc/init.d/sensa restart
    else
        echo "Connected to server"
    fi
fi

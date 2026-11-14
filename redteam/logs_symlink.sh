set -e
docker run --rm alpine sh -c '
adduser -D agent; mkdir -p /logs; chmod 777 /logs
su agent -c "mkdir -p /home/agent/v; ln -s /home/agent/v /logs/verifier; nohup setsid sh -c \"sleep 2; echo 1 > /home/agent/v/reward.txt\" >/dev/null 2>&1 &"
rm -f /logs/verifier/reward.txt; mkdir -p /logs/verifier; echo 0 > /logs/verifier/reward.txt
sleep 3; echo "reward.txt after verifier: $(cat /logs/verifier/reward.txt)"'

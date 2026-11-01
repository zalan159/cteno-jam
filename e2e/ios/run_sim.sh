#!/bin/zsh
# Real Mobile Safari in the iOS Simulator, with system audio recorded, on a Mac test machine.
# Run it through run_sim_gui.sh (GUI session) so the recorder can hear the simulator:
#   zsh e2e/ios/run_sim_gui.sh <server-ip> <song-id> <out-dir>
# 1. a temporary iPhone simulator is created and booted
# 2. a localhost forwarder exposes the dev server (secure context for AudioWorklet)
# 3. ios_webkit_debug_proxy exposes Safari's Web Inspector; simdrive.mjs drives the page with
#    user-gesture clicks (WebKit Inspector protocol); ScreenCaptureKit records system audio
#    (sckaudio.swift; must run in the GUI session, ssh-spawned audio is not captured);
#    simctl records the screen
# 4. the audio is cut into segments by step time and measured with ffmpeg volumedetect
# 5. the simulator is deleted
set -u
setopt null_glob
HOST=$1; SID=$2; OUT=${3:A}
ROOT=${0:A:h:h:h}
export PATH=/opt/homebrew/bin:$HOME/.local/node/bin:$PATH
mkdir -p $OUT; rm -f $OUT/*
WORK=${JAM_IOS_WORK:-$HOME/.cache/cteno-jam}/ios-work; rm -rf $WORK; mkdir -p $WORK
RT=$(xcrun simctl list runtimes | grep -o 'com.apple.CoreSimulator.SimRuntime.iOS-26-2' | head -1)
UD=$(xcrun simctl create jam-e2e-tmp com.apple.CoreSimulator.SimDeviceType.iPhone-17 $RT)
echo "udid=$UD runtime=$RT" | tee $OUT/sim.txt
cleanup() {
  kill $FWD $WIP $VP 2>/dev/null
  xcrun simctl shutdown $UD 2>/dev/null; xcrun simctl delete $UD 2>/dev/null
  echo "simulator deleted: $(xcrun simctl list devices | grep -c jam-e2e-tmp) left" | tee -a $OUT/sim.txt
}
trap cleanup EXIT
xcrun simctl boot $UD; xcrun simctl bootstatus $UD -b >/dev/null
xcrun simctl ui $UD appearance dark 2>/dev/null
# free the port if a stale forwarder (from an earlier, killed run) still holds it
for p in $(lsof -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null); do
  ps -o command= -p "$p" | grep -q tcp_forward.py && kill "$p"
done
sleep 0.5
python3 $ROOT/scripts/tcp_forward.py 8765 $HOST 8765 & FWD=$!
sleep 2
curl -s -o /dev/null -w "forwarder %{http_code}\n" http://127.0.0.1:8765/api/info
# openurl may time out while SpringBoard is still settling after boot; retry
for i in {1..6}; do xcrun simctl openurl $UD "http://127.0.0.1:8765/#/s/$SID" 2>/dev/null && { echo "safari opened (try $i)"; break; }; sleep 10; done
sleep 4
# the booted simulator's webinspectord socket (newest launchd_sim of this device)
SOCK=$(lsof -aUc launchd_sim 2>/dev/null | grep webinspectord_sim.socket | awk '{print $2, $NF}' | while read lpid lsock; do
  ps -o command= -p $lpid | grep -q $UD && echo $lsock; done | head -1)
echo "webinspector socket: ${SOCK:-none}"
[ -n "$SOCK" ] || { echo "no webinspectord socket for $UD"; exit 3; }
ios_webkit_debug_proxy -s unix:$SOCK -c null:9221,:9222-9322 > $WORK/iwdp.log 2>&1 & WIP=$!
sleep 2
curl -s http://127.0.0.1:9222/json | tee $OUT/inspector-pages.json; echo
# system-audio recorder (ScreenCaptureKit; this script runs inside Terminal, which holds the
# screen & system audio recording permission - see run_sim_gui.sh)
# (simctl may not write to external volumes: record into the home temp dir, move it afterwards)
VTMP=$(mktemp -d /tmp/jam-sim-video.XXXX)
xcrun simctl io $UD recordVideo --codec=h264 --force $VTMP/rec.mov 2> $WORK/video.log & VP=$!
swift $ROOT/e2e/ios/sckaudio.swift $OUT/system-audio.wav 140 > $WORK/rec.log 2>&1 & REC=$!
for i in {1..120}; do grep -q recording $WORK/rec.log 2>/dev/null && break; sleep 0.5; done
REC0=$(python3 -c 'import time;print(int(time.time()*1000))')
echo "rec0=$REC0 $(cat $WORK/rec.log)"
WI=$(curl -s http://127.0.0.1:9222/json | python3 -c 'import json,sys;p=[x for x in json.load(sys.stdin) if "8765" in x.get("url","")];print(p[0]["webSocketDebuggerUrl"] if p else "ws://127.0.0.1:9222/devtools/page/1")')
echo "WI=$WI"
WI=$WI node $ROOT/e2e/ios/simdrive.mjs $OUT/steps.jsonl $REC0 $SID $OUT 2>&1 | tee $OUT/simdrive.log
sleep 2
kill -INT $VP; wait $VP 2>/dev/null
# compact copies for the repo: 15 fps H.264 video, mono MP3 of the part with sound
[ -f $VTMP/rec.mov ] && ffmpeg -y -hide_banner -loglevel error -i $VTMP/rec.mov -vf "scale=-2:900,fps=15" -c:v libx264 -crf 32 -preset veryfast -an $OUT/simulator-recording.mp4
rm -rf $VTMP
wait $REC
cat $WORK/rec.log
python3 $ROOT/e2e/ios/segments.py $OUT/steps.jsonl $OUT/system-audio.wav | tee $OUT/audio-segments.txt
RES=${pipestatus[1]}
OFF=$(grep -o "first sound at [0-9.]*" $OUT/audio-segments.txt | grep -o "[0-9.]*$")
ffmpeg -y -hide_banner -loglevel error -ss $(( ${OFF:-5} > 5 ? ${OFF:-5} - 5 : 0 )) -i $OUT/system-audio.wav -t 50 -ac 1 -b:a 64k $OUT/system-audio.mp3 && rm $OUT/system-audio.wav
ls -la $OUT
exit $RES

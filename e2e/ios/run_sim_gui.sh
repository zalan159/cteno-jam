#!/bin/zsh
# Start run_sim.sh inside the logged-in GUI session (Terminal) and wait for it from ssh.
# Audio played by processes started from an ssh session is not visible to system-audio
# capture, so the simulator, Safari and the recorder must all live in the GUI session.
#   zsh e2e/ios/run_sim_gui.sh <server-ip> <song-id> <out-dir>
set -u
ROOT=${0:A:h:h:h}
OUT=${3:A}
WORK=${JAM_IOS_WORK:-$HOME/.cache/cteno-jam}/ios-gui; mkdir -p $WORK
rm -f $WORK/run.log $WORK/run.done
cat > $WORK/run.command <<EOF
#!/bin/zsh
cd $ROOT && zsh e2e/ios/run_sim.sh $1 $2 $OUT > $WORK/run.log 2>&1; echo \$? > $WORK/run.done; exit
EOF
chmod +x $WORK/run.command
open -g -a Terminal $WORK/run.command
for i in {1..900}; do [ -f $WORK/run.done ] && break; sleep 1; done
cat $WORK/run.log
echo "run_sim exit=$(cat $WORK/run.done 2>/dev/null || echo timeout)"
cp $WORK/run.log $OUT/run.log 2>/dev/null

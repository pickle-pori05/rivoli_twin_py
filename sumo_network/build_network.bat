@echo off
echo Compilation du reseau SUMO...
netconvert --node-files rivoli.nod.xml --edge-files rivoli.edg.xml --output-file rivoli.net.xml
echo Termine ! Le fichier rivoli.net.xml a ete cree.

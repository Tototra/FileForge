-- FileForge : clic = roue sur la sélection du Finder (ou zone de dépôt) ; glisser des fichiers sur l'icône = roue sur ces fichiers.
property launcher : "Library/Application Support/FileForge/run.sh"

on run
	do shell script quoted form of (POSIX path of (path to home folder) & launcher) & " > /dev/null 2>&1 &"
end run

on open fs
	set cmd to quoted form of (POSIX path of (path to home folder) & launcher)
	repeat with f in fs
		set cmd to cmd & " " & quoted form of (POSIX path of f)
	end repeat
	do shell script cmd & " > /dev/null 2>&1 &"
end open

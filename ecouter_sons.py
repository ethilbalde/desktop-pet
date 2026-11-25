"""Joue tous les sons du pet, un par un, au volume choisi (ex. : python ecouter_sons.py 10)."""
import sys
import time
import winsound
import araignee as A

vol = float(sys.argv[1]) / 100 if len(sys.argv) > 1 else 0.3
S = A.Sound()
S.set_volume(vol)
GROUPES = [('Interface', ['tap', 'pop', 'ding', 'clink', 'boing']),
           ('Araignee et proies', ['buzz', 'chirp', 'crunch', 'hiss']),
           ('Chat', ['meow', 'purr', 'snore']), ('Chien', ['woof', 'pant']),
           ('Chevre naine', ['bleat', 'bleat_s']), ('Furet', ['dook', 'dook_s'])]
print('Volume : %d %%' % round(S.volume * 100))
for titre, noms in GROUPES:
    print('--', titre)
    for n in noms:
        print('   ', n)
        winsound.PlaySound(S._path(n), winsound.SND_FILENAME)
        time.sleep(0.35)

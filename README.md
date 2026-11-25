# Araignée de bureau — un petit animal qui vit sur ton écran

Un compagnon animé qui se promène sur ton bureau Windows, par-dessus tes fenêtres, sans jamais bloquer la souris.

**Animaux :** araignée, chat, chien, chèvre naine, furet — chacun avec ses robes, ses comportements et ses sons.

## Le bug de ce projet : avoir un animal de compagnie

**Statut :** connu, reproductible à 100 %, ne sera pas corrigé (c'est la fonctionnalité).

**Symptômes**
- Tu commences à travailler, et dix minutes plus tard tu regardes une chèvre naine sauter de fenêtre en fenêtre.
- Tu secoues la souris « pour voir » : le furet part à tes trousses, le chien aboie, le chat te juge.
- Il se cache derrière ta fenêtre juste quand tu veux la déplacer, et s'endort sur celle que tu voulais fermer.
- Tu te surprends à poser la gamelle « parce qu'il a peut-être faim ».
- Tu dis « pas maintenant » à un animal qui n'existe pas.

**Cause :** un animal de compagnie, même en pixels, demande de l'attention, des caresses et un peu de nourriture. La documentation officielle n'a pas trouvé d'autre explication.

**Contournement :** clic droit > *Pause* (il arrête de bouger, il t'attend) ou *Quitter*. Fonctionne jusqu'au prochain lancement.

**Correctif définitif :** aucun connu. Les tentatives de désinstallation provoquent surtout de la culpabilité.

*Les vrais bugs (un animal coincé, un plantage...) sont les bienvenus dans l'onglet **Issues**.*

## Installation (la plus simple)

1. Va dans l'onglet **Releases** du dépôt et télécharge `AraigneeBureau.exe`.
2. Double-clique dessus. C'est tout, il n'y a rien à installer.
   - Windows peut afficher « Windows a protégé votre ordinateur » : clique sur **Informations complémentaires**, puis **Exécuter quand même** (l'exe n'est pas signé).
3. Pour l'arrêter : clic droit sur l'animal > **Quitter**.

Tes réglages sont enregistrés dans `%APPDATA%\AraigneeBureau`.

## Utilisation

- **Clic droit sur l'animal** : menu (Race, Pelage, Actions, Sortir, Donner à manger, Taille, Son...).
- **Prendre l'animal / la balle / la gamelle** : clic gauche maintenu, puis relâcher.
- **Caresser** : passe doucement la souris sur lui.
- **Clic droit sur le panier** : sortir des proies ou des jouets.
- Il peut sauter de fenêtre en fenêtre, grimper sur leurs bords et se cacher derrière celle du dessus.

Options de lancement : `--animal spider|cat|dog|goat|ferret`, `--monitor 2` (écran à utiliser), `--scale 1.5`.

## Lancer depuis les sources

Python 3.10+ sous Windows, aucune dépendance (tkinter est fourni avec Python).

```
python araignee.py --animal ferret
```

`lancer_araignee.bat` / `arreter_araignee.bat` démarrent et arrêtent le programme.

## Fabriquer l'exe soi-même

```
pip install pyinstaller
construire_exe.bat
```

Le fichier est produit dans `dist\AraigneeBureau.exe`.

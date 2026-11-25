# Araignée de bureau — un petit animal qui vit sur ton écran

Un compagnon animé qui se promène sur ton bureau Windows, par-dessus tes fenêtres, sans jamais bloquer la souris.

**Animaux :** araignée, chat, chien, chèvre naine, furet — chacun avec ses robes, ses comportements et ses sons.

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

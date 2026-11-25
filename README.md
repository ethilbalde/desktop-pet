# Un petit animal qui vit sur ton écran

> **Tu t'ennuies au bureau ?** Voici un petit animal pour te faire passer le temps.

### [⬇️ Télécharger AraigneeBureau.exe](https://github.com/ethilbalde/desktop-pet/releases/latest/download/AraigneeBureau.exe)

*Windows 10/11 · un seul fichier · rien à installer, aucune dépendance · toujours la dernière version.*

> **Avertissement :** ce logiciel ne sert à rien. Il fait ça très bien.

Tu as un rapport à rendre ? Parfait. Il a justement besoin d'attention.

C'est un petit animal qui s'installe sur ton bureau Windows, se balade par-dessus tes fenêtres, grimpe dessus, se cache derrière, et n'a qu'**un seul but dans la vie : te distraire**. Il ne bloque jamais ta souris. Il bloque juste ta productivité.

## Le casting

| | Qui | Sa spécialité |
|---|---|---|
| 🕷️ | **L'araignée** | Tisse une toile dans un coin de l'écran pendant que tu ne regardes pas. Danse quand elle est contente. Ne demande rien, observe tout. |
| 🐱 | **Le chat** | Te juge. Se cache dans sa boîte en carton. Fait tomber ta tasse du bord de la fenêtre en te regardant droit dans les yeux. |
| 🐶 | **Le chien** | T'aime. Beaucoup. Tout le temps. Rapporte la balle même quand tu ne l'as pas lancée. |
| 🐐 | **La chèvre naine** | Pique des crises de folie sans prévenir, saute partout et donne des coups de tête aux fenêtres. Personne ne sait pourquoi. Elle non plus. |
| 🦦 | **Le furet** | Va trop vite. Chasse ton curseur comme si c'était un ennemi personnel. Fait « dook-dook ». |

Chacun a plusieurs pelages, des grimaces (yeux qui louchent, cœurs dans les yeux, langue tirée...) et un **caractère tiré au sort à la naissance** : gourmand, paresseux, câlin, colérique, farceur, cochon... Oui, tu peux tomber sur un furet paresseux et cochon. Non, on ne rembourse pas.

## Comme un Tamagotchi (en moins culpabilisant)

- Il naît d'un **œuf**. Tu cliques dessus pour l'aider à éclore, puis **tu lui donnes un nom**.
- Il grandit : bébé, jeune, adulte, senior.
- Il a faim, sommeil, envie de jouer, et il se salit. Tu peux le nourrir, le laver, le soigner et le caresser (passe doucement la souris sur lui).
- Il tombe malade si tu l'oublies trop longtemps, mais **il ne meurt jamais**. Ce logiciel est là pour te distraire, pas pour te faire pleurer.
- Envie d'un autre ? **Animal > Nouvel animal** : l'ancien est rangé dans tes sauvegardes, pas abandonné. On n'est pas des monstres.

## Effets secondaires fréquents

*Comme pour tout animal de compagnie, lis attentivement cette notice.*

- Tu commences à travailler, et dix minutes plus tard tu regardes une chèvre naine sauter de fenêtre en fenêtre.
- Tu secoues la souris « pour voir » : le furet part à tes trousses, le chien aboie, le chat te juge.
- Il se cache derrière ta fenêtre juste quand tu veux la déplacer, et s'endort sur celle que tu voulais fermer.
- Tu poses la gamelle « parce qu'il a peut-être faim ».
- Tu lui dis « pas maintenant ». Il s'en fiche.
- Tu as passé plus de temps à choisir son nom que le prénom de ton premier enfant.
- Sourires inexpliqués en pleine réunion.

**Besoin de concentration ?** Clic droit > *Réglages* > *Pause* : il s'arrête et t'attend sagement (en te fixant avec de grands yeux). Ou *Quitter*, mais il sera content de te revoir au prochain lancement.

**Un vrai problème ?** (un animal coincé, un plantage...) Signale-le directement depuis le programme : clic droit sur le **panier** > **Sortir** > **Signaler un bug**. Ton navigateur ouvre un ticket déjà rempli, tu n'as plus qu'à l'envoyer.

## Installation (30 secondes, dont 25 à hésiter)

1. Clique sur [**Télécharger AraigneeBureau.exe**](https://github.com/ethilbalde/desktop-pet/releases/latest/download/AraigneeBureau.exe) (ou va dans l'onglet **Releases**).
2. Double-clique dessus. C'est tout : **rien à installer, aucun Python, aucune dépendance**. Tout est dans le fichier.
   - Windows peut afficher « Windows a protégé votre ordinateur » : clique sur **Informations complémentaires**, puis **Exécuter quand même**. L'exe n'est pas signé, l'animal non plus.
3. Choisis ton animal et son pelage dans le menu de lancement. Un œuf apparaît.
4. Adieu productivité.

**Mettre à jour :** *Réglages* > *Mise à jour*. Il télécharge la dernière version depuis GitHub et redémarre, **sans oublier ton animal** (âge, nom, caractère, tout est gardé).

**Désinstaller (si tu en as le cœur) :** quitte le programme, supprime `AraigneeBureau.exe`, puis le dossier `%APPDATA%\AraigneeBureau` où vivent ses souvenirs. Il ne laisse rien d'autre sur ton PC, pas même une petite crotte.

## Mode d'emploi

- **Clic droit sur l'animal** : le menu. Onglets *État* (jauges, nom, soins), *Actions*, *Sortir*, *Animal* (race, pelage, nouvel animal, charger) et *Réglages* (taille et volume en curseurs, qualité, écran, mise à jour).
- **Clic gauche maintenu** : tu l'attrapes. Il n'aime pas trop, mais il ne dira rien.
- **Double-clic** : saut périlleux.
- **Secouer la souris** : lance une course-poursuite. Le furet considère ça comme une déclaration de guerre.
- **Clic sur le panier** : sort un jouet. **Clic droit sur le panier** : proies, balle, boîte en carton.
- Il saute de fenêtre en fenêtre, grimpe sur leurs bords et se cache derrière celle du dessus. Comme un vrai.
- Il disparaît tout seul quand tu lances un jeu ou une vidéo en plein écran. Il a du savoir-vivre.

## Pour les développeurs (et les curieux)

Python 3.10+ sous Windows. Pillow sert à lisser le dessin (sans lui ça marche, avec des bords en escalier) :

```
pip install pillow
python araignee.py
```

Options : `--animal spider|cat|dog|goat|ferret`, `--monitor 2`, `--scale 1.5`, `--direct` (sans le menu de lancement).

Fabriquer l'exe soi-même :

```
pip install pyinstaller pillow
construire_exe.bat
```

Le fichier sort dans `dist\AraigneeBureau.exe`. Aucun animal n'a été maltraité pendant la compilation.

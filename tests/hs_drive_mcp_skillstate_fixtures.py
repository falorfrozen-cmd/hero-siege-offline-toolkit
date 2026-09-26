"""Replies the plugin printed in live 2 of the skill research, byte for byte.

Cut by a script, never typed, from
`.claude/workorders/hs-drive-stash-bag-actions-live-2-ipc.md` in the toolkit
checkout: the stash workorder's byte copy of the game's `bp_ipc` `out.txt`
after the shared live-2 launch of 2026-09-25 (ForgePact research build
`01510ed`, `BloodPactPlugin_rel.dll` sha256 `ea3f38f5...92fa`, save slot 14;
the copy is 1,430,977 bytes, sha256
`878e997aac6dcb43b3c0fc0871574be1fed128627f3cf1bd8ae38f3747998ceb`). Each
constant runs from a `---- running command file ----` line to the next
`---- done ----` line, both included, CRLF, as `ipc.send` returns a reply;
its comment names the copy's line (1-based, as `grep -n` counts) the frame
starts on. The copy is local (`.claude/workorders/` is untracked), so
whether each constant is still a substring of it is a workorder criterion,
not a unit test: the tests only use the constants.

These are runtime data the plugin printed, not game source. They are string
constants rather than data files so git's line-ending conversion cannot turn
them into a reply no live run produced. Do not hand-edit a line: cut again.

`skillprobe state` is the research build's reader. The player build's
`skillstate` prints the same body lines under a `skillstate:` header, adds an
`effect=` field to a slot whose ability has a `kSkillTimerNames` entry, and
leaves out the research-only `hud.playerSlot`, `level=` and `points?` lines,
so the hub's parser was tested on `skillprobe state` frames until live 3.

`LIVE3_FIXTURES` below are `skillstate` itself, cut the same way from
`.claude/workorders/hs-drive-skill-actions-live-3-ipc.md` in the toolkit
checkout: the skill workorder's byte copy of the game's `bp_ipc` `out.txt`
after live 3 of 2026-09-26 (ForgePact player build `BloodPactPlugin.dll`
sha256 `57aba60cc820e6a0362080b84f89d5a0150d0666458638bee8acacb40007bffc`;
the copy is 1,656,842 bytes, sha256
`79c3c45cf314c151e34ad90da0f598450e9c46fc50a3e8fd0df3e1e3320599f6`).
"""

#: `skillprobe state` at K1, before any hand action: fifteen talents on the bar (0,0 `darkOath` 242), `global.mySkills` twelve ids, a `sub=` line per bar talent - the shape `skillstate` copies.
#: The copy's line 3886 onward.
SKILLPROBE_STATE_K1 = (
    "---- running command file ----\r\n"
    "skillprobe state:\r\n"
    "  slot=0,0 talent=242 ability=darkOath timer=127\r\n"
    "  slot=0,1 talent=0 ability=unreadable timer=96\r\n"
    "  slot=0,2 talent=250 ability=chainOfHolyLight timer=85\r\n"
    "  slot=0,3 talent=253 ability=manaOrb timer=161\r\n"
    "  slot=0,4 talent=252 ability=healingZone timer=113\r\n"
    "  slot=0,5 talent=240 ability=soulSpurn timer=31\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=71\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=143\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=98\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=51\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=56\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=5\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=107\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=112\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=100\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=61\r\n"
    "  slot=1,3 talent=237 ability=restlessSpirits timer=46\r\n"
    "  slot=1,4 talent=239 ability=shadowBolt timer=163\r\n"
    "  slot=1,5 talent=240 ability=soulSpurn timer=21\r\n"
    "  slot=1,6 talent=242 ability=darkOath timer=29\r\n"
    "  slot=1,7 talent=245 ability=heavenlyFire timer=15\r\n"
    "  slot=1,8 talent=246 ability=burstOfLight timer=131\r\n"
    "  slot=1,9 talent=247 ability=flashHeal timer=78\r\n"
    "  slot=1,10 talent=250 ability=chainOfHolyLight timer=16\r\n"
    "  slot=1,11 talent=251 ability=holyShield timer=65\r\n"
    "  slot=1,12 talent=252 ability=healingZone timer=48\r\n"
    "  slot=1,13 talent=253 ability=manaOrb timer=74\r\n"
    "  slot=1,14 talent=492 ability=recallSummons timer=122\r\n"
    "  slot=1,15 talent=493 ability=commandMinions timer=99\r\n"
    "  global.mySkills=[236,237,239,240,242,245,246,247,250,251,252,253]\r\n"
    "  hud.playerSlot.bind_skill=undefined\r\n"
    "  sub=242 s3=5 s4=5 s1=5 s8=2 s11=3 s12=0 s13=0 s10=0\r\n"
    "  sub=250 s4=2 s8=2 s7=2 s2=2 s5=2 s12=3 s6=2 s10=5\r\n"
    "  sub=253 s4=5 s1=2 s8=2 s7=1 s2=2 s5=0 s9=0 s12=3 s6=5 s10=0\r\n"
    "  sub=252 none\r\n"
    "  sub=240 s7=5 s2=2 s9=5 s12=3 s6=2 s10=3\r\n"
    "  sub=1 none\r\n"
    "  sub=236 s6=2 s3=0 s4=0 s1=5 s8=0 s7=2 s2=5 s5=3 s9=0 s11=0 s12=0 s14=3\r\n"
    "  sub=237 s4=2 s1=5 s8=3 s2=5 s9=0 s11=0 s12=0 s13=3 s10=2\r\n"
    "  sub=239 s6=0 s10=5 s4=5 s1=5 s8=2 s2=0 s9=0 s11=3 s12=0 s13=0 s14=0\r\n"
    "  sub=245 s4=2 s8=2 s7=5 s2=2 s5=2 s12=3 s14=0 s6=4\r\n"
    "  sub=246 none\r\n"
    "  sub=247 none\r\n"
    "  sub=251 none\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "  level=242 unreadable (script_execute threw)\r\n"
    "  level=250 unreadable (script_execute threw)\r\n"
    "  level=253 unreadable (script_execute threw)\r\n"
    "  level=252 unreadable (script_execute threw)\r\n"
    "  level=240 unreadable (script_execute threw)\r\n"
    "  level=1 unreadable (script_execute threw)\r\n"
    "  level=236 unreadable (script_execute threw)\r\n"
    "  level=237 unreadable (script_execute threw)\r\n"
    "  level=239 unreadable (script_execute threw)\r\n"
    "  level=245 unreadable (script_execute threw)\r\n"
    "  level=246 unreadable (script_execute threw)\r\n"
    "  level=247 unreadable (script_execute threw)\r\n"
    "  level=251 unreadable (script_execute threw)\r\n"
    "  level=492 unreadable (script_execute threw)\r\n"
    "  level=493 unreadable (script_execute threw)\r\n"
    "  points? player: no numeric member whose name contains point, talent or skill\r\n"
    "skillprobe state: 15 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillprobe state` after the owner's Reset Skills: `global.mySkills=[236]` - the allocation's baseline.
#: The copy's line 12181 onward.
SKILLPROBE_STATE_AFTER_RESET = (
    "---- running command file ----\r\n"
    "skillprobe state:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=141\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=1\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=15\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=121\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=173\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=49\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=67\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=30\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=27\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=83\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=114\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=94\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=10\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=33\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=87\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=169\r\n"
    "  slot=1,3 talent=492 ability=recallSummons timer=7\r\n"
    "  slot=1,4 talent=493 ability=commandMinions timer=42\r\n"
    "  global.mySkills=[236]\r\n"
    "  hud.playerSlot.bind_skill=undefined\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "  level=1 unreadable (script_execute threw)\r\n"
    "  level=236 unreadable (script_execute threw)\r\n"
    "  level=492 unreadable (script_execute threw)\r\n"
    "  level=493 unreadable (script_execute threw)\r\n"
    "  points? player: no numeric member whose name contains point, talent or skill\r\n"
    "skillprobe state: 4 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillprobe state` after the by-name `UiATalentScreenTalent` on 239: `global.mySkills=[236,239]`, `sub=239 s2=0` - the allocation's target and the sub-allocation's baseline.
#: The copy's line 12424 onward.
SKILLPROBE_STATE_AFTER_ALLOC = (
    "---- running command file ----\r\n"
    "skillprobe state:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=131\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=24\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=108\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=56\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=82\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=133\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=52\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=88\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=135\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=39\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=25\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=117\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=3\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=45\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=41\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=87\r\n"
    "  slot=1,3 talent=239 ability=shadowBolt timer=111\r\n"
    "  slot=1,4 talent=492 ability=recallSummons timer=130\r\n"
    "  slot=1,5 talent=493 ability=commandMinions timer=119\r\n"
    "  global.mySkills=[236,239]\r\n"
    "  hud.playerSlot.bind_skill=undefined\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=239 s2=0\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "  level=1 unreadable (script_execute threw)\r\n"
    "  level=236 unreadable (script_execute threw)\r\n"
    "  level=239 unreadable (script_execute threw)\r\n"
    "  level=492 unreadable (script_execute threw)\r\n"
    "  level=493 unreadable (script_execute threw)\r\n"
    "  points? player: no numeric member whose name contains point, talent or skill\r\n"
    "skillprobe state: 5 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillprobe state` after the by-name `UiAActivateSkillSubPoint` on the second listed node: `sub=239 s1=1 s2=0` - the sub-allocation's target.
#: The copy's line 12468 onward.
SKILLPROBE_STATE_AFTER_SUB = (
    "---- running command file ----\r\n"
    "skillprobe state:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=32\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=100\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=17\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=120\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=22\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=28\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=88\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=112\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=44\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=90\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=78\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=144\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=36\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=89\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=120\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=168\r\n"
    "  slot=1,3 talent=239 ability=shadowBolt timer=5\r\n"
    "  slot=1,4 talent=492 ability=recallSummons timer=70\r\n"
    "  slot=1,5 talent=493 ability=commandMinions timer=159\r\n"
    "  global.mySkills=[236,239]\r\n"
    "  hud.playerSlot.bind_skill=undefined\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=239 s1=1 s2=0\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "  level=1 unreadable (script_execute threw)\r\n"
    "  level=236 unreadable (script_execute threw)\r\n"
    "  level=239 unreadable (script_execute threw)\r\n"
    "  level=492 unreadable (script_execute threw)\r\n"
    "  level=493 unreadable (script_execute threw)\r\n"
    "  points? player: no numeric member whose name contains point, talent or skill\r\n"
    "skillprobe state: 5 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Hud_Talent_obj`: one bar row (`id=262341`) and its 29 `slot=` rows (row 0 slots 0-12, row 1 slots 0-15).
#: The copy's line 10736 onward.
MENULAYOUT_HUD = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Hud_Talent_obj id=262341 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none enabled=1 text=\r\n"
    "  slot=0,0 talent=242 gui=7.6,1121.0 win=6,885\r\n"
    "  slot=0,1 talent=0 gui=195.7,1259.7 win=147,994\r\n"
    "  slot=0,2 talent=250 gui=277.4,1259.7 win=208,994\r\n"
    "  slot=0,3 talent=253 gui=89.3,1121.0 win=67,885\r\n"
    "  slot=0,4 talent=252 gui=171.0,1121.0 win=128,885\r\n"
    "  slot=0,5 talent=240 gui=252.7,1121.0 win=190,885\r\n"
    "  slot=0,6 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,7 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,8 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,9 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,10 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,11 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=0,12 talent=0 gui=-1.9,0.0 win=-1,0\r\n"
    "  slot=1,0 talent=0 gui=89.3,1029.8 win=67,813\r\n"
    "  slot=1,1 talent=1 gui=171.0,1029.8 win=128,813\r\n"
    "  slot=1,2 talent=236 gui=252.7,1029.8 win=190,813\r\n"
    "  slot=1,3 talent=237 gui=334.4,1029.8 win=251,813\r\n"
    "  slot=1,4 talent=239 gui=416.1,1029.8 win=312,813\r\n"
    "  slot=1,5 talent=240 gui=497.8,1029.8 win=373,813\r\n"
    "  slot=1,6 talent=242 gui=7.6,1029.8 win=6,813\r\n"
    "  slot=1,7 talent=245 gui=579.5,1029.8 win=435,813\r\n"
    "  slot=1,8 talent=246 gui=661.2,1029.8 win=496,813\r\n"
    "  slot=1,9 talent=247 gui=742.9,1029.8 win=557,813\r\n"
    "  slot=1,10 talent=250 gui=89.3,938.6 win=67,741\r\n"
    "  slot=1,11 talent=251 gui=171.0,938.6 win=128,741\r\n"
    "  slot=1,12 talent=252 gui=252.7,938.6 win=190,741\r\n"
    "  slot=1,13 talent=253 gui=334.4,938.6 win=251,741\r\n"
    "  slot=1,14 talent=492 gui=416.1,938.6 win=312,741\r\n"
    "  slot=1,15 talent=493 gui=497.8,938.6 win=373,741\r\n"
    "menulayout: listed=1 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Button_Talent_Player_obj` with the screen open: 18 rows, each with `name=` and `talentId=` (`id=275481 talentId=239`; `name=Black Mass` with `talentId=244`).
#: The copy's line 12303 onward.
MENULAYOUT_TALENT_BUTTONS = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275479 gui=1380.7,452.2 win=1036,357 bbox=1380.7,452.2,1458.6,530.1 visible=1 sprite=Talent_Martyr_spr name=Martyr uiNodeCallstack=TalentScreenTalent1 activationArgs=[] enabled=1 talentId=241 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275481 gui=1646.7,452.2 win=1235,357 bbox=1646.7,452.2,1724.6,530.1 visible=1 sprite=Talent_Shadow_Bolt_spr name=Shadow Bolt uiNodeCallstack=TalentScreenTalent3 activationArgs=[] enabled=1 talentId=239 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275483 gui=1380.7,577.6 win=1036,456 bbox=1380.7,577.6,1458.6,655.5 visible=1 sprite=Talent_Digest_Souls_spr name=Digest Souls uiNodeCallstack=TalentScreenTalent4 activationArgs=[] enabled=1 talentId=238 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275484 gui=1515.6,577.6 win=1137,456 bbox=1515.6,577.6,1593.5,655.5 visible=1 sprite=Talent_Soul_Spurn_spr name=Soul Spurn uiNodeCallstack=TalentScreenTalent5 activationArgs=[] enabled=1 talentId=240 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275487 gui=1380.7,699.2 win=1036,552 bbox=1380.7,699.2,1458.6,777.1 visible=1 sprite=Talent_Restless_Spirits_spr name=Restless Spirits uiNodeCallstack=TalentScreenTalent7 activationArgs=[] enabled=1 talentId=237 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275489 gui=1515.6,699.2 win=1137,552 bbox=1515.6,699.2,1593.5,777.1 visible=1 sprite=Talent_Dark_Oath_spr name=Dark Oath uiNodeCallstack=TalentScreenTalent8 activationArgs=[] enabled=1 talentId=242 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275493 gui=1515.6,820.8 win=1137,648 bbox=1515.6,820.8,1593.5,898.7 visible=1 sprite=Talent_Satans_Mark_spr name=Satan\u2019s Mark uiNodeCallstack=TalentScreenTalent11 activationArgs=[] enabled=1 talentId=236 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275495 gui=1646.7,820.8 win=1235,648 bbox=1646.7,820.8,1724.6,898.7 visible=1 sprite=Talent_Malediction_spr name=Malediction uiNodeCallstack=TalentScreenTalent12 activationArgs=[] enabled=1 talentId=243 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275497 gui=1515.6,942.4 win=1137,744 bbox=1515.6,942.4,1593.5,1020.3 visible=1 sprite=Talent_Black_Mass_spr name=Black Mass uiNodeCallstack=TalentScreenTalent14 activationArgs=[] enabled=1 talentId=244 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275500 gui=1889.9,452.2 win=1417,357 bbox=1889.9,452.2,1967.8,530.1 visible=1 sprite=Talent_Heavenly_Fire_spr name=Heavenly Fire uiNodeCallstack=TalentScreenTalent16 activationArgs=[] enabled=1 talentId=245 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275503 gui=2155.9,452.2 win=1617,357 bbox=2155.9,452.2,2233.8,530.1 visible=1 sprite=Talent_Flash_Heal_spr name=Flash Heal uiNodeCallstack=TalentScreenTalent18 activationArgs=[] enabled=1 talentId=247 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275504 gui=1889.9,577.6 win=1417,456 bbox=1889.9,577.6,1967.8,655.5 visible=1 sprite=Talent_Burst_of_Light_spr name=Burst of Light uiNodeCallstack=TalentScreenTalent19 activationArgs=[] enabled=1 talentId=246 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275506 gui=2024.8,577.6 win=1519,456 bbox=2024.8,577.6,2102.7,655.5 visible=1 sprite=Talent_Divine_Healing_spr name=Divine Healing uiNodeCallstack=TalentScreenTalent20 activationArgs=[] enabled=1 talentId=249 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275508 gui=1889.9,699.2 win=1417,552 bbox=1889.9,699.2,1967.8,777.1 visible=1 sprite=Talent_Chain_of_Holy_Light_spr name=Chain of Holy Lightning uiNodeCallstack=TalentScreenTalent22 activationArgs=[] enabled=1 talentId=250 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275511 gui=2155.9,699.2 win=1617,552 bbox=2155.9,699.2,2233.8,777.1 visible=1 sprite=Talent_Holy_Shield_spr name=Holy Shield uiNodeCallstack=TalentScreenTalent24 activationArgs=[] enabled=1 talentId=251 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275513 gui=2024.8,820.8 win=1519,648 bbox=2024.8,820.8,2102.7,898.7 visible=1 sprite=Talent_Benediction_spr name=Benediction uiNodeCallstack=TalentScreenTalent26 activationArgs=[] enabled=1 talentId=248 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275514 gui=2155.9,820.8 win=1617,648 bbox=2155.9,820.8,2233.8,898.7 visible=1 sprite=Talent_Healing_Zone_spr name=Healing Zone uiNodeCallstack=TalentScreenTalent27 activationArgs=[] enabled=1 talentId=252 text=\r\n"
    "  obj=UI_Button_Talent_Player_obj id=275515 gui=1889.9,942.4 win=1417,744 bbox=1889.9,942.4,1967.8,1020.3 visible=1 sprite=Talent_Mana_Orb_spr name=Mana Orb uiNodeCallstack=TalentScreenTalent28 activationArgs=[] enabled=1 talentId=253 text=\r\n"
    "menulayout: listed=18 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Button_Sub_Skill_obj`: 10 rows (`id=275482 talentId=239`).
#: The copy's line 12369 onward.
MENULAYOUT_SUB_SKILL_BUTTONS = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275482 gui=1739.8,469.3 win=1305,370 bbox=1724.6,454.1,1755.0,484.5 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent3 activationArgs=[] enabled=1 talentId=239 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275485 gui=1608.7,594.7 win=1207,470 bbox=1593.5,579.5,1623.9,609.9 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent5 activationArgs=[] enabled=1 talentId=240 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275488 gui=1473.8,716.3 win=1105,565 bbox=1458.6,701.1,1489.0,731.5 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent7 activationArgs=[] enabled=1 talentId=237 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275490 gui=1608.7,716.3 win=1207,565 bbox=1593.5,701.1,1623.9,731.5 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent8 activationArgs=[] enabled=1 talentId=242 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275494 gui=1608.7,837.9 win=1207,662 bbox=1593.5,822.7,1623.9,853.1 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent11 activationArgs=[] enabled=1 talentId=236 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275498 gui=1608.7,959.5 win=1207,758 bbox=1593.5,944.3,1623.9,974.7 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent14 activationArgs=[] enabled=1 talentId=244 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275501 gui=1983.0,469.3 win=1487,370 bbox=1967.8,454.1,1998.2,484.5 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent16 activationArgs=[] enabled=1 talentId=245 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275505 gui=1983.0,594.7 win=1487,470 bbox=1967.8,579.5,1998.2,609.9 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent19 activationArgs=[] enabled=1 talentId=246 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275509 gui=1983.0,716.3 win=1487,565 bbox=1967.8,701.1,1998.2,731.5 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent22 activationArgs=[] enabled=1 talentId=250 text=\r\n"
    "  obj=UI_Button_Sub_Skill_obj id=275516 gui=1983.0,959.5 win=1487,758 bbox=1967.8,944.3,1998.2,974.7 visible=1 sprite=UI_Button_Sub_Skill_spr uiNodeCallstack=TalentScreenSubTalent28 activationArgs=[] enabled=1 talentId=253 text=\r\n"
    "menulayout: listed=10 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Button_Subtalent_obj` with 239's sub-panel open: 15 nodes, `Big` and `Small` sprites, no name field.
#: The copy's line 12397 onward.
MENULAYOUT_SUBTALENT_NODES = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Subtalent_obj id=275677 gui=1280.0,1140.0 win=960,900 bbox=1238.2,1098.2,1321.8,1181.8 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Big_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275678 gui=1228.7,999.4 win=922,789 bbox=1202.1,972.8,1255.3,1026.0 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275679 gui=1331.3,999.4 win=998,789 bbox=1304.7,972.8,1357.9,1026.0 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275680 gui=1061.5,874.0 win=796,690 bbox=1034.9,847.4,1088.1,900.6 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275681 gui=1181.2,870.2 win=886,687 bbox=1154.6,843.6,1207.8,896.8 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275682 gui=1283.8,870.2 win=963,687 bbox=1257.2,843.6,1310.4,896.8 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275683 gui=1386.4,870.2 win=1040,687 bbox=1359.8,843.6,1413.0,896.8 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275684 gui=1500.4,870.2 win=1125,687 bbox=1473.8,843.6,1527.0,896.8 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275685 gui=1129.9,712.5 win=847,563 bbox=1103.3,685.9,1156.5,739.1 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275686 gui=1430.1,712.5 win=1073,563 bbox=1403.5,685.9,1456.7,739.1 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275687 gui=1287.6,615.6 win=966,486 bbox=1261.0,589.0,1314.2,642.2 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Small_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275688 gui=920.9,877.8 win=691,693 bbox=879.1,836.0,962.7,919.6 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Big_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275689 gui=1063.4,463.6 win=798,366 bbox=1021.6,421.8,1105.2,505.4 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Big_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275690 gui=1509.9,463.6 win=1132,366 bbox=1468.1,421.8,1551.7,505.4 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Big_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Subtalent_obj id=275691 gui=1644.8,868.3 win=1234,685 bbox=1603.0,826.5,1686.6,910.1 visible=1 sprite=Sub_WhiteMage_Shadow_Bolt_Big_spr uiNodeCallstack= activationArgs=[] enabled=1 text=\r\n"
    "menulayout: listed=15 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Talent_Screen_obj` with the screen open: `listed=1` (`id=275195`).
#: The copy's line 12504 onward.
MENULAYOUT_TALENT_SCREEN_OPEN = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Talent_Screen_obj id=275195 gui=0.0,0.0 win=0,0 bbox=-13.0,-10.0,13.0,10.0 visible=1 sprite=Bubble_Talent_spr enabled=1 text=\r\n"
    "menulayout: listed=1 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: `menulayout UI_Talent_Screen_obj` after the close: `listed=0`.
#: The copy's line 12686 onward.
MENULAYOUT_TALENT_SCREEN_CLOSED = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "menulayout: listed=0 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: Every live-2 frame above.
LIVE2_FIXTURES = (
    SKILLPROBE_STATE_K1,
    SKILLPROBE_STATE_AFTER_RESET,
    SKILLPROBE_STATE_AFTER_ALLOC,
    SKILLPROBE_STATE_AFTER_SUB,
    MENULAYOUT_HUD,
    MENULAYOUT_TALENT_BUTTONS,
    MENULAYOUT_SUB_SKILL_BUTTONS,
    MENULAYOUT_SUBTALENT_NODES,
    MENULAYOUT_TALENT_SCREEN_OPEN,
    MENULAYOUT_TALENT_SCREEN_CLOSED,
)

#: `skillstate` W1's first read: 0,0 `darkOath` effect=0, 0,3 `manaOrb` effect=0, twelve learned ids.
#: The copy's line 13578 onward.
SKILLSTATE_W1_FIRST_READ = (
    "---- running command file ----\r\n"
    "skillstate:\r\n"
    "  slot=0,0 talent=242 ability=darkOath timer=84 effect=0\r\n"
    "  slot=0,1 talent=0 ability=unreadable timer=43\r\n"
    "  slot=0,2 talent=250 ability=chainOfHolyLight timer=66 effect=0\r\n"
    "  slot=0,3 talent=253 ability=manaOrb timer=66 effect=0\r\n"
    "  slot=0,4 talent=252 ability=healingZone timer=121 effect=0\r\n"
    "  slot=0,5 talent=240 ability=soulSpurn timer=53 effect=0\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=87\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=52\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=56\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=89\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=63\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=60\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=28\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=99\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=74\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=119 effect=0\r\n"
    "  slot=1,3 talent=237 ability=restlessSpirits timer=10\r\n"
    "  slot=1,4 talent=239 ability=shadowBolt timer=54 effect=0\r\n"
    "  slot=1,5 talent=240 ability=soulSpurn timer=129 effect=0\r\n"
    "  slot=1,6 talent=242 ability=darkOath timer=72 effect=0\r\n"
    "  slot=1,7 talent=245 ability=heavenlyFire timer=85 effect=0\r\n"
    "  slot=1,8 talent=246 ability=burstOfLight timer=36 effect=0\r\n"
    "  slot=1,9 talent=247 ability=flashHeal timer=100\r\n"
    "  slot=1,10 talent=250 ability=chainOfHolyLight timer=76 effect=0\r\n"
    "  slot=1,11 talent=251 ability=holyShield timer=43\r\n"
    "  slot=1,12 talent=252 ability=healingZone timer=111 effect=0\r\n"
    "  slot=1,13 talent=253 ability=manaOrb timer=12 effect=0\r\n"
    "  slot=1,14 talent=492 ability=recallSummons timer=34\r\n"
    "  slot=1,15 talent=493 ability=commandMinions timer=45\r\n"
    "  global.mySkills=[236,237,239,240,242,245,246,247,250,251,252,253]\r\n"
    "  sub=242 s3=5 s4=5 s1=5 s8=2 s11=3 s12=0 s13=0 s10=0\r\n"
    "  sub=250 s4=2 s8=2 s7=2 s2=2 s5=2 s12=3 s6=2 s10=5\r\n"
    "  sub=253 s4=5 s1=2 s8=2 s7=1 s2=2 s5=0 s9=0 s12=3 s6=5 s10=0\r\n"
    "  sub=252 none\r\n"
    "  sub=240 s7=5 s2=2 s9=5 s12=3 s6=2 s10=3\r\n"
    "  sub=1 none\r\n"
    "  sub=236 s6=2 s3=0 s4=0 s1=5 s8=0 s7=2 s2=5 s5=3 s9=0 s11=0 s12=0 s14=3\r\n"
    "  sub=237 s4=2 s1=5 s8=3 s2=5 s9=0 s11=0 s12=0 s13=3 s10=2\r\n"
    "  sub=239 s6=0 s10=5 s4=5 s1=5 s8=2 s2=0 s9=0 s11=3 s12=0 s13=0 s14=0\r\n"
    "  sub=245 s4=2 s8=2 s7=5 s2=2 s5=2 s12=3 s14=0 s6=4\r\n"
    "  sub=246 none\r\n"
    "  sub=247 none\r\n"
    "  sub=251 none\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "skillstate: 15 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillstate` after live 3's first Q press: 0,3 `manaOrb` `timer=53 effect=1` (1,13 also 1), 0,0 still 0 - the player build's positive control.
#: The copy's line 13872 onward.
SKILLSTATE_POST_Q_PRESS = (
    "---- running command file ----\r\n"
    "skillstate:\r\n"
    "  slot=0,0 talent=242 ability=darkOath timer=110 effect=0\r\n"
    "  slot=0,1 talent=0 ability=unreadable timer=103\r\n"
    "  slot=0,2 talent=250 ability=chainOfHolyLight timer=89 effect=0\r\n"
    "  slot=0,3 talent=253 ability=manaOrb timer=53 effect=1\r\n"
    "  slot=0,4 talent=252 ability=healingZone timer=95 effect=0\r\n"
    "  slot=0,5 talent=240 ability=soulSpurn timer=27 effect=0\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=17\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=19\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=88\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=27\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=1\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=29\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=121\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=7\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=90\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=166 effect=0\r\n"
    "  slot=1,3 talent=237 ability=restlessSpirits timer=57\r\n"
    "  slot=1,4 talent=239 ability=shadowBolt timer=99 effect=0\r\n"
    "  slot=1,5 talent=240 ability=soulSpurn timer=67 effect=0\r\n"
    "  slot=1,6 talent=242 ability=darkOath timer=86 effect=0\r\n"
    "  slot=1,7 talent=245 ability=heavenlyFire timer=55 effect=0\r\n"
    "  slot=1,8 talent=246 ability=burstOfLight timer=31 effect=0\r\n"
    "  slot=1,9 talent=247 ability=flashHeal timer=65\r\n"
    "  slot=1,10 talent=250 ability=chainOfHolyLight timer=56 effect=0\r\n"
    "  slot=1,11 talent=251 ability=holyShield timer=23\r\n"
    "  slot=1,12 talent=252 ability=healingZone timer=68 effect=0\r\n"
    "  slot=1,13 talent=253 ability=manaOrb timer=52 effect=1\r\n"
    "  slot=1,14 talent=492 ability=recallSummons timer=46\r\n"
    "  slot=1,15 talent=493 ability=commandMinions timer=72\r\n"
    "  global.mySkills=[236,237,239,240,242,245,246,247,250,251,252,253]\r\n"
    "  sub=242 s3=5 s4=5 s1=5 s8=2 s11=3 s12=0 s13=0 s10=0\r\n"
    "  sub=250 s4=2 s8=2 s7=2 s2=2 s5=2 s12=3 s6=2 s10=5\r\n"
    "  sub=253 s4=5 s1=2 s8=2 s7=1 s2=2 s5=0 s9=0 s12=3 s6=5 s10=0\r\n"
    "  sub=252 none\r\n"
    "  sub=240 s7=5 s2=2 s9=5 s12=3 s6=2 s10=3\r\n"
    "  sub=1 none\r\n"
    "  sub=236 s6=2 s3=0 s4=0 s1=5 s8=0 s7=2 s2=5 s5=3 s9=0 s11=0 s12=0 s14=3\r\n"
    "  sub=237 s4=2 s1=5 s8=3 s2=5 s9=0 s11=0 s12=0 s13=3 s10=2\r\n"
    "  sub=239 s6=0 s10=5 s4=5 s1=5 s8=2 s2=0 s9=0 s11=3 s12=0 s13=0 s14=0\r\n"
    "  sub=245 s4=2 s8=2 s7=5 s2=2 s5=2 s12=3 s14=0 s6=4\r\n"
    "  sub=246 none\r\n"
    "  sub=247 none\r\n"
    "  sub=251 none\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "skillstate: 15 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillstate` after W5's main allocation: `global.mySkills=[236,244]`, `sub=244 none`; slot 0,0 reads `talent=0` (the owner's Reset Skills emptied the bar).
#: The copy's line 14763 onward.
SKILLSTATE_POST_MAIN_ALLOC = (
    "---- running command file ----\r\n"
    "skillstate:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=52\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=65\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=60\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=45\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=65\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=53\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=68\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=58\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=70\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=69\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=44\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=68\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=39\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=65\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=70\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=68 effect=0\r\n"
    "  slot=1,3 talent=244 ability=blackMass timer=56\r\n"
    "  slot=1,4 talent=492 ability=recallSummons timer=65\r\n"
    "  slot=1,5 talent=493 ability=commandMinions timer=67\r\n"
    "  global.mySkills=[236,244]\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=244 none\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "skillstate: 5 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillstate` after W5's sub allocation: `sub=244 s1=1`.
#: The copy's line 14834 onward.
SKILLSTATE_POST_SUB_ALLOC = (
    "---- running command file ----\r\n"
    "skillstate:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=142\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=101\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=73\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=102\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=59\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=110\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=70\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=73\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=60\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=103\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=115\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=47\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=49\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=78\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=62\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=151 effect=0\r\n"
    "  slot=1,3 talent=244 ability=blackMass timer=158\r\n"
    "  slot=1,4 talent=492 ability=recallSummons timer=150\r\n"
    "  slot=1,5 talent=493 ability=commandMinions timer=93\r\n"
    "  global.mySkills=[236,244]\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=244 s1=1\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "skillstate: 5 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: `skillstate` at W6, after the reload: `[236,244]` and `sub=244 s1=1` both persisted.
#: The copy's line 15113 onward.
SKILLSTATE_POST_RELOAD_W6 = (
    "---- running command file ----\r\n"
    "skillstate:\r\n"
    "  slot=0,0 talent=0 ability=unreadable timer=97\r\n"
    "  slot=0,1 talent=1 ability=basicAttack timer=65\r\n"
    "  slot=0,2 talent=1 ability=basicAttack timer=67\r\n"
    "  slot=0,3 talent=0 ability=unreadable timer=27\r\n"
    "  slot=0,4 talent=0 ability=unreadable timer=54\r\n"
    "  slot=0,5 talent=0 ability=unreadable timer=16\r\n"
    "  slot=0,6 talent=0 ability=unreadable timer=57\r\n"
    "  slot=0,7 talent=0 ability=unreadable timer=66\r\n"
    "  slot=0,8 talent=0 ability=unreadable timer=67\r\n"
    "  slot=0,9 talent=0 ability=unreadable timer=55\r\n"
    "  slot=0,10 talent=0 ability=unreadable timer=36\r\n"
    "  slot=0,11 talent=0 ability=unreadable timer=51\r\n"
    "  slot=0,12 talent=0 ability=unreadable timer=64\r\n"
    "  slot=1,0 talent=0 ability=unreadable timer=55\r\n"
    "  slot=1,1 talent=1 ability=basicAttack timer=71\r\n"
    "  slot=1,2 talent=236 ability=satansMark timer=34 effect=0\r\n"
    "  slot=1,3 talent=244 ability=blackMass timer=62\r\n"
    "  slot=1,4 talent=492 ability=recallSummons timer=82\r\n"
    "  slot=1,5 talent=493 ability=commandMinions timer=70\r\n"
    "  global.mySkills=[236,244]\r\n"
    "  sub=1 none\r\n"
    "  sub=236 none\r\n"
    "  sub=244 s1=1\r\n"
    "  sub=492 none\r\n"
    "  sub=493 none\r\n"
    "skillstate: 5 talent(s) on the bar\r\n"
    "---- done ----\r\n")

#: Every live-3 frame above.
LIVE3_FIXTURES = (
    SKILLSTATE_W1_FIRST_READ,
    SKILLSTATE_POST_Q_PRESS,
    SKILLSTATE_POST_MAIN_ALLOC,
    SKILLSTATE_POST_SUB_ALLOC,
    SKILLSTATE_POST_RELOAD_W6,
)

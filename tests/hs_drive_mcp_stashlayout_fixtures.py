"""The stash and bag `menulayout` replies live 2 captured from a running game.

Verbatim, byte for byte, from the plugin's own `bp_ipc/out.txt` of the live-2 session
(2026-09-25, ForgePact research build `BloodPactPlugin_rel.dll` from `01510ed`,
sha256 `EA3F38F5...92FA`, slot 14 in `Town_01_rm`, 1920x1080 windowed client;
`ForgePact/docs/stash-bag-layout-research.md` § Results, P2-2 to P2-7), as copied
to `.claude/workorders/hs-drive-stash-bag-actions-live-2-ipc.md` before any later
launch rotated it (workorder `hs-drive-stash-bag-actions`, Step 4b; taken here in
Step 4). Each is one reply as `ipc.send` reads it: framed by
`---- running command file ----` / `---- done ----`, CRLF. These lines are runtime
data the plugin printed, not game source.

The research build's `menulayout` is the player build's: the stash tools read
these rows the same way. Rows predate Step 5's additions (`tabSelected` and the
`cell=` rows), which live 3 captures. Do not hand-edit a row: re-capture instead.
"""

#: P2-2 (live 2 attempt 2): `menulayout UI_Stash_obj` straight after the interact key F opened the stash - `id=262983`, `stashTabSelected=0` (the Personal tab). Lines 8993-8997 of the copy.
STASH_WINDOW_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Stash_obj id=262983 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none enabled=1 stashTabSelected=0 text=\r\n"
    "menulayout: listed=1 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: P2-3 (live 2 attempt 2): `menulayout UI_Button_Stash_Tab_obj` on the same window, 23 rows keyed by `tabNumber`. The file holds no listing of these rows after the Materials switch, so this is the one taken with Personal on show (`stashTabSelected=0`); the rows carry no selection state either way. Lines 9057-9083 of the copy.
STASH_TABS_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263031 gui=1150.4,89.3 win=863,71 bbox=1150.4,89.3,1211.2,144.4 visible=0 sprite=Inventory_Tab_Square_Button_spr uiNodeCallstack=StashTabSocket activationArgs=[-2,<ref>] enabled=1 tabNumber=-2 tabType=1 text=Socketable\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263032 gui=1210.4,89.3 win=908,71 bbox=1210.4,89.3,1271.2,144.4 visible=0 sprite=Inventory_Tab_Square_Button_spr uiNodeCallstack=StashTabMaterial activationArgs=[-4,<ref>] enabled=1 tabNumber=-4 tabType=1 text=Materials\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263033 gui=1038.4,89.3 win=779,71 bbox=1038.4,89.3,1150.8,144.4 visible=0 sprite=Unique_Stash_Tab_Button_spr uiNodeCallstack=StashUnique activationArgs=[-5,<ref>] enabled=1 tabNumber=-5 tabType=1 text=Unique\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263034 gui=125.4,89.3 win=94,71 bbox=125.4,89.3,247.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_1 activationArgs=[0,<ref>] enabled=1 tabNumber=0 tabType=2 text=Personal\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263035 gui=246.4,89.3 win=185,71 bbox=246.4,89.3,357.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_2 activationArgs=[1,<ref>] enabled=1 tabNumber=1 tabType=2 text=Shared1\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263036 gui=356.4,89.3 win=267,71 bbox=356.4,89.3,470.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_3 activationArgs=[2,<ref>] enabled=1 tabNumber=2 tabType=2 text=Shared2\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263037 gui=469.4,89.3 win=352,71 bbox=469.4,89.3,583.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_4 activationArgs=[3,<ref>] enabled=1 tabNumber=3 tabType=2 text=Shared3\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263038 gui=582.4,89.3 win=437,71 bbox=582.4,89.3,697.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_5 activationArgs=[4,<ref>] enabled=1 tabNumber=4 tabType=2 text=Shared4\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263039 gui=696.4,89.3 win=522,71 bbox=696.4,89.3,810.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_6 activationArgs=[5,<ref>] enabled=1 tabNumber=5 tabType=2 text=Shared5\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263040 gui=809.4,89.3 win=607,71 bbox=809.4,89.3,926.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_7 activationArgs=[6,<ref>] enabled=1 tabNumber=6 tabType=2 text=Shared6\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263041 gui=925.4,89.3 win=694,71 bbox=925.4,89.3,1039.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_8 activationArgs=[7,<ref>] enabled=1 tabNumber=7 tabType=2 text=Shared7\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263042 gui=1270.4,89.3 win=953,71 bbox=1270.4,89.3,1397.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_9 activationArgs=[8,<ref>] enabled=1 tabNumber=8 tabType=2 text=Shared8\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263043 gui=1397.4,89.3 win=1048,71 bbox=1397.4,89.3,1524.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_10 activationArgs=[9,<ref>] enabled=1 tabNumber=9 tabType=2 text=Shared9\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263044 gui=1524.4,89.3 win=1143,71 bbox=1524.4,89.3,1661.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_11 activationArgs=[10,<ref>] enabled=1 tabNumber=10 tabType=2 text=Shared10\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263045 gui=1661.4,89.3 win=1246,71 bbox=1661.4,89.3,1792.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_12 activationArgs=[11,<ref>] enabled=1 tabNumber=11 tabType=2 text=Shared11\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263046 gui=1792.4,89.3 win=1344,71 bbox=1792.4,89.3,1926.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_13 activationArgs=[12,<ref>] enabled=1 tabNumber=12 tabType=2 text=Shared12\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263047 gui=1926.4,89.3 win=1445,71 bbox=1926.4,89.3,2060.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_14 activationArgs=[13,<ref>] enabled=1 tabNumber=13 tabType=2 text=Shared13\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263048 gui=2060.4,89.3 win=1545,71 bbox=2060.4,89.3,2195.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_15 activationArgs=[14,<ref>] enabled=1 tabNumber=14 tabType=2 text=Shared14\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263049 gui=2195.4,89.3 win=1647,71 bbox=2195.4,89.3,2329.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_16 activationArgs=[15,<ref>] enabled=1 tabNumber=15 tabType=2 text=Shared15\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263050 gui=2329.4,89.3 win=1747,71 bbox=2329.4,89.3,2466.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_17 activationArgs=[16,<ref>] enabled=1 tabNumber=16 tabType=2 text=Shared16\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263051 gui=2466.4,89.3 win=1850,71 bbox=2466.4,89.3,2600.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_18 activationArgs=[17,<ref>] enabled=1 tabNumber=17 tabType=2 text=Shared17\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263052 gui=2600.4,89.3 win=1950,71 bbox=2600.4,89.3,2736.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_19 activationArgs=[18,<ref>] enabled=1 tabNumber=18 tabType=2 text=Shared18\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=263053 gui=2736.4,89.3 win=2052,71 bbox=2736.4,89.3,2872.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_20 activationArgs=[19,<ref>] enabled=1 tabNumber=19 tabType=2 text=Shared19\r\n"
    "menulayout: listed=23 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: P2-4 (live 2 attempt 2): `menulayout UI_Button_Inventory_Tab_Small_obj`, the bag's 7 sub-tab rows beside the open stash, keyed by `uiNodeCallstack` (`InventoryTabMaterial` = id 263017, `InventoryTabSocket` = id 263016). Lines 9486-9496 of the copy.
BAG_SUBTABS_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263014 gui=1665.1,1198.9 win=1249,947 bbox=1665.1,1198.9,1756.3,1261.6 visible=1 sprite=Inventory_Tab_Small_Button_spr uiNodeCallstack=InventoryTabVault activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263015 gui=1573.9,1198.9 win=1180,947 bbox=1573.9,1198.9,1665.1,1261.6 visible=1 sprite=Inventory_Tab_Small_Button_spr uiNodeCallstack=InventoryTabVaultActive activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263016 gui=1756.3,1198.9 win=1317,947 bbox=1756.3,1198.9,1830.4,1261.6 visible=1 sprite=Inventory_Tab_Smaller_Button_spr uiNodeCallstack=InventoryTabSocket activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263017 gui=1828.5,1198.9 win=1371,947 bbox=1828.5,1198.9,1902.6,1261.6 visible=1 sprite=Inventory_Tab_Smaller_Button_spr uiNodeCallstack=InventoryTabMaterial activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263018 gui=1900.7,1198.9 win=1426,947 bbox=1900.7,1198.9,1974.8,1261.6 visible=1 sprite=Inventory_Tab_Smaller_Button_spr uiNodeCallstack=InventoryTabKey activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263019 gui=1972.9,1198.9 win=1480,947 bbox=1972.9,1198.9,2047.0,1261.6 visible=1 sprite=Inventory_Tab_Smaller_Button_spr uiNodeCallstack=InventoryTabTarot activationArgs=[] enabled=1 text=\r\n"
    "  obj=UI_Button_Inventory_Tab_Small_obj id=263020 gui=2045.1,1198.9 win=1534,947 bbox=2045.1,1198.9,2119.2,1261.6 visible=1 sprite=Inventory_Tab_Smaller_Button_spr uiNodeCallstack=InventoryTabRelic activationArgs=[] enabled=1 text=\r\n"
    "menulayout: listed=7 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: P2-7 (live 2 attempt 2): `menulayout UI_Button_Close_obj` - the stash's close row, id 263010, `uiNodeCallstack=InventoryClose`. Lines 10563-10567 of the copy.
STASH_CLOSE_BUTTON_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Close_obj id=263010 gui=1592.9,34.2 win=1195,27 bbox=1573.9,15.2,1613.8,55.1 visible=1 sprite=Button_Close_spr uiNodeCallstack=InventoryClose activationArgs=[] enabled=1 text=\r\n"
    "menulayout: listed=1 absent=none capped=0\r\n"
    "---- done ----\r\n")

#: Live 2 attempt 1 (the same DLL, the window before the crash): one send carrying six `menulayout <Obj>` lines - `UI_Stash_obj`, `UI_Button_Stash_Tab_obj`, `UI_Button_Inventory_Tab_obj`, `UI_Inventory_Grid_obj`, `UI_Inventory_Drag_obj` and an object with no instance - so six listings in one reply, the shape the stash tools send. Lines 3136-3186 of the copy.
MULTI_LISTING_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Stash_obj id=264071 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none enabled=1 stashTabSelected=0 text=\r\n"
    "menulayout: listed=1 absent=none capped=0\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264119 gui=1150.4,89.3 win=863,71 bbox=1150.4,89.3,1211.2,144.4 visible=0 sprite=Inventory_Tab_Square_Button_spr uiNodeCallstack=StashTabSocket activationArgs=[-2,<ref>] enabled=1 tabNumber=-2 tabType=1 text=Socketable\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264120 gui=1210.4,89.3 win=908,71 bbox=1210.4,89.3,1271.2,144.4 visible=0 sprite=Inventory_Tab_Square_Button_spr uiNodeCallstack=StashTabMaterial activationArgs=[-4,<ref>] enabled=1 tabNumber=-4 tabType=1 text=Materials\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264121 gui=1038.4,89.3 win=779,71 bbox=1038.4,89.3,1150.8,144.4 visible=0 sprite=Unique_Stash_Tab_Button_spr uiNodeCallstack=StashUnique activationArgs=[-5,<ref>] enabled=1 tabNumber=-5 tabType=1 text=Unique\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264122 gui=125.4,89.3 win=94,71 bbox=125.4,89.3,247.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_1 activationArgs=[0,<ref>] enabled=1 tabNumber=0 tabType=2 text=Personal\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264123 gui=246.4,89.3 win=185,71 bbox=246.4,89.3,357.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_2 activationArgs=[1,<ref>] enabled=1 tabNumber=1 tabType=2 text=Shared1\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264124 gui=356.4,89.3 win=267,71 bbox=356.4,89.3,470.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_3 activationArgs=[2,<ref>] enabled=1 tabNumber=2 tabType=2 text=Shared2\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264125 gui=469.4,89.3 win=352,71 bbox=469.4,89.3,583.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_4 activationArgs=[3,<ref>] enabled=1 tabNumber=3 tabType=2 text=Shared3\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264126 gui=582.4,89.3 win=437,71 bbox=582.4,89.3,697.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_5 activationArgs=[4,<ref>] enabled=1 tabNumber=4 tabType=2 text=Shared4\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264127 gui=696.4,89.3 win=522,71 bbox=696.4,89.3,810.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_6 activationArgs=[5,<ref>] enabled=1 tabNumber=5 tabType=2 text=Shared5\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264128 gui=809.4,89.3 win=607,71 bbox=809.4,89.3,926.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_7 activationArgs=[6,<ref>] enabled=1 tabNumber=6 tabType=2 text=Shared6\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264129 gui=925.4,89.3 win=694,71 bbox=925.4,89.3,1039.2,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_8 activationArgs=[7,<ref>] enabled=1 tabNumber=7 tabType=2 text=Shared7\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264130 gui=1270.4,89.3 win=953,71 bbox=1270.4,89.3,1397.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_9 activationArgs=[8,<ref>] enabled=1 tabNumber=8 tabType=2 text=Shared8\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264131 gui=1397.4,89.3 win=1048,71 bbox=1397.4,89.3,1524.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_10 activationArgs=[9,<ref>] enabled=1 tabNumber=9 tabType=2 text=Shared9\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264132 gui=1524.4,89.3 win=1143,71 bbox=1524.4,89.3,1661.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_11 activationArgs=[10,<ref>] enabled=1 tabNumber=10 tabType=2 text=Shared10\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264133 gui=1661.4,89.3 win=1246,71 bbox=1661.4,89.3,1792.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_12 activationArgs=[11,<ref>] enabled=1 tabNumber=11 tabType=2 text=Shared11\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264134 gui=1792.4,89.3 win=1344,71 bbox=1792.4,89.3,1926.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_13 activationArgs=[12,<ref>] enabled=1 tabNumber=12 tabType=2 text=Shared12\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264135 gui=1926.4,89.3 win=1445,71 bbox=1926.4,89.3,2060.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_14 activationArgs=[13,<ref>] enabled=1 tabNumber=13 tabType=2 text=Shared13\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264136 gui=2060.4,89.3 win=1545,71 bbox=2060.4,89.3,2195.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_15 activationArgs=[14,<ref>] enabled=1 tabNumber=14 tabType=2 text=Shared14\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264137 gui=2195.4,89.3 win=1647,71 bbox=2195.4,89.3,2329.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_16 activationArgs=[15,<ref>] enabled=1 tabNumber=15 tabType=2 text=Shared15\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264138 gui=2329.4,89.3 win=1747,71 bbox=2329.4,89.3,2466.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_17 activationArgs=[16,<ref>] enabled=1 tabNumber=16 tabType=2 text=Shared16\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264139 gui=2466.4,89.3 win=1850,71 bbox=2466.4,89.3,2600.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_18 activationArgs=[17,<ref>] enabled=1 tabNumber=17 tabType=2 text=Shared17\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264140 gui=2600.4,89.3 win=1950,71 bbox=2600.4,89.3,2736.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_19 activationArgs=[18,<ref>] enabled=1 tabNumber=18 tabType=2 text=Shared18\r\n"
    "  obj=UI_Button_Stash_Tab_obj id=264141 gui=2736.4,89.3 win=2052,71 bbox=2736.4,89.3,2872.6,144.4 visible=0 sprite=Stash_Tab_Button_spr uiNodeCallstack=StashTab_20 activationArgs=[19,<ref>] enabled=1 tabNumber=19 tabType=2 text=Shared19\r\n"
    "menulayout: listed=23 absent=none capped=0\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Button_Inventory_Tab_obj id=264109 gui=1573.9,1136.2 win=1180,897 bbox=1573.9,1136.2,1756.3,1198.9 visible=1 sprite=Inventory_Tab_Button_Main_spr uiNodeCallstack=InventoryTab_1 activationArgs=[] enabled=1 tabNumber=0 tabType=1 text=Main\r\n"
    "  obj=UI_Button_Inventory_Tab_obj id=264110 gui=1756.3,1136.2 win=1317,897 bbox=1756.3,1136.2,1938.7,1198.9 visible=1 sprite=Inventory_Tab_Button_Main_spr uiNodeCallstack=InventoryTab_2 activationArgs=[] enabled=1 tabNumber=1 tabType=1 text=Extra\r\n"
    "  obj=UI_Button_Inventory_Tab_obj id=264111 gui=1938.7,1136.2 win=1454,897 bbox=1938.7,1136.2,2121.1,1198.9 visible=1 sprite=Inventory_Tab_Button_Main_spr uiNodeCallstack=InventoryTab_3 activationArgs=[] enabled=1 tabNumber=2 tabType=1 text=Extra\r\n"
    "  obj=UI_Button_Inventory_Tab_obj id=264112 gui=2121.1,1136.2 win=1591,897 bbox=2121.1,1136.2,2303.5,1198.9 visible=1 sprite=Inventory_Tab_Button_Main_spr uiNodeCallstack=InventoryTab_4 activationArgs=[] enabled=1 tabNumber=3 tabType=1 text=Extra\r\n"
    "  obj=UI_Button_Inventory_Tab_obj id=264113 gui=2303.5,1136.2 win=1728,897 bbox=2303.5,1136.2,2485.9,1198.9 visible=1 sprite=Inventory_Tab_Button_Main_spr uiNodeCallstack=InventoryTab_5 activationArgs=[] enabled=1 tabNumber=4 tabType=1 text=Extra\r\n"
    "menulayout: listed=5 absent=none capped=0\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Inventory_Grid_obj id=257745 gui=357.2,1337.6 win=268,1056 bbox=357.2,1337.6,358.2,1338.6 visible=1 sprite=none uiNodeCallstack=PotionGrid activationArgs=[] enabled=0 nodeGridWidth=4 nodeGridHeight=1 gridScale=0.5 gridName= text=\r\n"
    "  obj=UI_Inventory_Grid_obj id=264097 gui=1822.8,695.4 win=1367,549 bbox=1822.8,695.4,1823.8,696.4 visible=1 sprite=none uiNodeCallstack=PotionGrid activationArgs=[] enabled=1 nodeGridWidth=4 nodeGridHeight=1 gridScale=1 gridName= text=\r\n"
    "  obj=UI_Inventory_Grid_obj id=264099 gui=1572.0,765.7 win=1179,605 bbox=1572.0,765.7,2484.0,1130.5 visible=1 sprite=none uiNodeCallstack=InventoryGrid activationArgs=[] enabled=1 nodeGridWidth=15 nodeGridHeight=6 gridScale=1 gridName= text=\r\n"
    "  obj=UI_Inventory_Grid_obj id=264100 gui=2303.5,76.0 win=1728,60 bbox=2303.5,76.0,2485.9,744.8 visible=1 sprite=none uiNodeCallstack=InventoryCharmGrid activationArgs=[] enabled=1 nodeGridWidth=3 nodeGridHeight=11 gridScale=1 gridName= text=\r\n"
    "  obj=UI_Inventory_Grid_obj id=264101 gui=1883.6,856.9 win=1413,677 bbox=1883.6,856.9,1884.6,857.9 visible=0 sprite=none uiNodeCallstack=InventoryVaultActiveGrid0 activationArgs=[] enabled=0 nodeGridWidth=5 nodeGridHeight=3 gridScale=1 gridName= text=\r\n"
    "  obj=UI_Inventory_Grid_obj id=264143 gui=76.0,222.3 win=57,176 bbox=76.0,222.3,1109.6,1316.7 visible=1 sprite=none uiNodeCallstack=StashGrid activationArgs=[] enabled=1 nodeGridWidth=17 nodeGridHeight=18 gridScale=1 gridName= text=\r\n"
    "menulayout: listed=6 absent=none capped=0\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "  obj=UI_Inventory_Drag_obj id=257744 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none text=\r\n"
    "  obj=UI_Inventory_Drag_obj id=264073 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none text=\r\n"
    "menulayout: listed=2 absent=none capped=0\r\n"
    "menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=244.0,268.0,1280.0,720.0\r\n"
    "menulayout: listed=0 absent=none capped=0\r\n"
    "---- done ----\r\n")

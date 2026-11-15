"""临时改仿真场地，方便只测一个目标。

物块布局写死在 gongchuang_sim/scripts/build_field.py 里，而且渲染用 field.glb、
物理用 gripper_manual.sdf，两套都要动：
- SDF 里删掉其它物块，物理上只剩一个；
- Godot 里按环境变量 GC_ONLY_BLOCK 只显示指定物块。
改之前各留一份 .bak，随时可以还原。

用法：
    python tools/sim/field.py one-green     # 物理和画面都只留一个绿块
    python tools/sim/field.py restore       # 还原
"""

import argparse
import re
import shutil
from pathlib import Path

DEFAULT_SIM = Path(r"D:\my_project\gongchuang_sim")
BLOCKS = re.compile(r'\n\s*<model name="block_(?!green_01")[^"]*">.*?</model>', re.S)
MARK = '    # GC_ONLY_BLOCK：只显示指定物块，供单项测试用'
SNIPPET = '''
    var only := OS.get_environment("GC_ONLY_BLOCK")
    if only != "":
        for node in field.find_children("block_*", "", true, false):
            if not String(node.name).begins_with(only):
                node.visible = false
'''


def patch_stream(script, backup):
    """给 gripper_stream.gd 插入只显示一个物块的开关，重复执行不会重复插。"""
    if not backup.exists():
        shutil.copy2(script, backup)
    text = backup.read_text(encoding='utf-8')
    if MARK in text:
        return False
    anchor = '    super._ready()\n'
    if anchor not in text:
        raise SystemExit('gripper_stream.gd 结构变了，找不到 super._ready()')
    script.write_text(text.replace(anchor, anchor + MARK + SNIPPET, 1), encoding='utf-8')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('one-green', 'restore'))
    parser.add_argument('--sim-root', type=Path, default=DEFAULT_SIM)
    args = parser.parse_args()

    world = args.sim_root / 'worlds/gripper_manual.sdf'
    world_backup = world.with_suffix('.sdf.bak')
    script = args.sim_root / 'native_render/scripts/gripper_stream.gd'
    script_backup = script.with_suffix('.gd.bak')

    if args.action == 'restore':
        for path, backup in ((world, world_backup), (script, script_backup)):
            if backup.exists():
                shutil.copy2(backup, path)
                print(f'[Field] 已还原 {path}')
            else:
                print(f'[Field] 没有备份，跳过 {path}')
        return

    if not world_backup.exists():
        shutil.copy2(world, world_backup)
    text = world_backup.read_text(encoding='utf-8')
    text, removed = BLOCKS.subn('', text)
    world.write_text(text, encoding='utf-8')
    patched = patch_stream(script, script_backup)
    print(f'[Field] 物理移除 {removed} 个物块，只留 block_green_01')
    print(f'[Field] Godot 开关{"已插入" if patched else "已存在"}，启动时设 GC_ONLY_BLOCK=block_green_01')


if __name__ == '__main__':
    main()

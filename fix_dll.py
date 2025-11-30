import os
import shutil
import site
import glob


def fix_dll_v2():
    print("🚀 开始全自动修复 DLL 缺失问题 (V2)...")

    current_dir = os.getcwd()
    site_packages = site.getsitepackages()

    # 我们需要寻找的目标库及其对应的 DLL 模式
    targets = [
        # (包名子路径, 需要复制的文件模式)
        (os.path.join("nvidia", "cudnn", "bin"), "cudnn*.dll"),
        (os.path.join("nvidia", "cublas", "bin"), "cublas*.dll"),
    ]

    total_copied = 0

    for sub_path, pattern in targets:
        found_path = None
        # 在所有 site-packages 中寻找
        for sp in site_packages:
            check_path = os.path.join(sp, sub_path)
            if os.path.exists(check_path):
                found_path = check_path
                break

        if not found_path:
            print(f"❌ 未找到路径: .../{sub_path}")
            print(f"   -> 可能需要运行: pip install nvidia-{sub_path.split(os.sep)[1]}-cu12")
            continue

        print(f"📂 扫描目录: {found_path}")

        # 查找所有匹配的 dll
        dll_files = glob.glob(os.path.join(found_path, pattern))

        for file_path in dll_files:
            filename = os.path.basename(file_path)
            dest = os.path.join(current_dir, filename)

            if not os.path.exists(dest):
                try:
                    shutil.copy(file_path, dest)
                    print(f"   ✅ 已复制: {filename}")
                    total_copied += 1
                except Exception as e:
                    print(f"   ⚠️ 复制失败 {filename}: {e}")
            else:
                # print(f"   Pass: {filename} 已存在")
                pass

    print("-" * 30)
    if total_copied > 0:
        print(f"🎉 修复完成！共复制了 {total_copied} 个新文件。")
    else:
        print("🤔 没有复制新文件 (可能已经存在)。")

    print("👉 请再次尝试运行您的字幕脚本！")


if __name__ == "__main__":
    fix_dll_v2()
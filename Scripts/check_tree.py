import os
import re

class TreeNode:
    """
    用于表示树结构的节点。
    name: 节点名称
    children: {子节点名称: TreeNode对象}
    """
    def __init__(self, name):
        self.name = name
        self.children = {}

def parse_tree_file(filepath):
    """
    从目录树文件中解析出树结构，返回一个虚拟根节点 (TreeNode)。
    目录树文件格式假设类似：
    |——根目录
    |   |-media
    |   |   |-电视剧
    |   |   ...
    等等。

    注意：如果文件格式与示例中不完全一致，需要根据实际情况修改解析逻辑。

    这里我们显式使用 encoding='utf-16' 打开文件。
    如果你的文件是 UTF-16-LE 或 BE，可以改用 'utf-16-le' 或 'utf-16-be'。
    """
    root = TreeNode("虚拟根")  # 用来挂载所有第一层节点
    stack = [(root, -1)]       # (TreeNode, depth)

    # 用于匹配行首的缩进符号，例如: "|   |   |-" 等
    # 这里用一个简单的正则，若与你的实际格式不符，请相应调整
    # pattern = re.compile(r"^(?P<indent>[\|\s\-]+)(?P<name>.+)$")
    pattern = re.compile(r"^(?P<indent>[|\s\-]+)(?P<name>.+)$")

    with open(filepath, 'r', encoding='utf-16') as f:
        for line in f:
            line = line.rstrip('\n').rstrip()
            if not line:
                continue

            # 如果该行有像 "|——"、"|- " 的格式
            match = pattern.match(line)
            if match:
                indent_str = match.group("indent")  # 行首缩进符
                name_str = match.group("name")      # 实际名称

                # 计算层级，简单地根据 '|' 的数量来计算
                depth = indent_str.count('|')

                # 去掉前面可能的 "-"、"——"、空格等
                name_str = re.sub(r"^[\-—]+", "", name_str).strip()

                # 创建一个节点
                node = TreeNode(name_str)

                # 通过与栈顶对比层级，找到父节点
                while stack and stack[-1][1] >= depth:
                    stack.pop()

                if stack:
                    parent_node, _ = stack[-1]
                    parent_node.children[name_str] = node
                    stack.append((node, depth))
            else:
                # 若不匹配，可能是第一层（无缩进），直接处理
                # 假设没有 "| " 符号、只有纯文字时处理
                line_clean = line.lstrip("|\- ").strip()
                if line_clean:
                    # 默认当作深度=0
                    node = TreeNode(line_clean)
                    # 将该节点挂到根下面
                    root.children[line_clean] = node
                    stack = [(root, -1), (node, 0)]

    return root

def find_node_by_name(root: TreeNode, target_name: str) -> TreeNode | None:
    """
    在整棵树root下，递归搜索名称为 target_name 的节点。
    找到则返回该节点，否则返回 None。
    """
    if root.name == target_name:
        return root
    for child in root.children.values():
        result = find_node_by_name(child, target_name)
        if result:
            return result
    return None

def build_local_tree(path):
    """
    从本地文件夹 path 出发，递归构建 TreeNode 形式的树结构，并返回根节点。
    根节点名称采用 path 的最后一级目录名。
    """
    root_name = os.path.basename(path.rstrip("\\/"))
    root_node = TreeNode(root_name)

    try:
        for entry in os.scandir(path):
            if entry.is_dir():
                sub_node = build_local_tree(entry.path)
                root_node.children[sub_node.name] = sub_node
            else:
                file_node = TreeNode(entry.name)
                root_node.children[file_node.name] = file_node
    except PermissionError:
        # 若没有权限访问，可根据需要处理
        pass

    return root_node

def compare_trees(node_tree: TreeNode, node_local: TreeNode, diff_log: list, path=""):
    """
    比对两棵树（node_tree vs node_local），只比较名称。
    node_tree: 目录树文件中的 TreeNode
    node_local: 本地文件夹构建的 TreeNode
    diff_log: 用于存储差异信息的列表
    path: 当前比对层级在日志中的前缀 (相对路径)，用于更清晰的输出
    """
    # 取出子节点名称集合
    tree_children_names = set(node_tree.children.keys())
    local_children_names = set(node_local.children.keys())

    # 目录树文件多出的项
    only_in_tree = tree_children_names - local_children_names
    # 本地多出的项
    only_in_local = local_children_names - tree_children_names
    # 两边都有的项
    both = tree_children_names & local_children_names

    if only_in_tree:
        for name in sorted(only_in_tree):
            diff_log.append(f"[目录树文件多出] {path}/{name}")

    if only_in_local:
        for name in sorted(only_in_local):
            diff_log.append(f"[本地多出] {path}/{name}")

    # 递归比对两边都存在的节点
    for name in sorted(both):
        child_tree = node_tree.children[name]
        child_local = node_local.children[name]

        # 若任意一方没有子节点，则视为文件，或者也可以根据需要更精细的判断
        # 如果都还有 children（或不为空），才递归下去
        if child_tree.children or child_local.children:
            compare_trees(child_tree, child_local, diff_log, path + "/" + name)

def main(tree_file_path,local_file_path):
    """
    示例主函数。
    """

    # 1) 解析目录树文件 (UTF-16)
    full_tree = parse_tree_file(tree_file_path)

    # 2) 在解析后的树中，找到要对比的节点 (例如 "media")
    media_node = find_node_by_name(full_tree, "media")
    if not media_node:
        print("在目录树文件中未找到 'media' 节点，无法进行比对。")
        return

    # 3) 构建本地目录的树结构
    local_root = build_local_tree(local_file_path)

    # 4) 比对
    diff_log = []
    # path 参数初始可直接写"media"或其他自定义名称
    # 注意 local_root.name 也应该是 "media"
    compare_trees(media_node, local_root, diff_log, path="media")

    # 5) 输出差异结果
    if not diff_log:
        print("两边目录结构一致，没有发现差异。")
    else:
        print("发现差异如下：")
        for line in diff_log:
            print(line)

if __name__ == "__main__":
    # 指定目录树文件(默认使用 UTF-16 编码) 和 本地文件夹路径
    tree_file = r"C:\Users\ZSW\Downloads\tree.txt"
    local_path = r"Z:\Media\media"
    main(tree_file, local_path)

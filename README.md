# 📚 图书推荐系统 - 数据处理文档

> **当前分支：`data-processing`**  
> 本分支仅用于数据处理实验，**最终数据集已同步到 `main/data/`**

---

## 🎯 分支说明

这是**数据处理专用分支**，包含从亚马逊原始数据到最终训练集的全流程代码。

| 分支 | 用途 | 是否上传CSV |
|------|------|------------|
| `data-processing` | 数据处理实验、代码开发 | ❌ 不上传原始数据 |
| `main` | Django项目、最终数据集 | ✅ 已上传 train.csv & metadata.csv |

**✅ 如果你只需要使用数据集，请直接拉取 `main/data/` 目录！**

---

## 📁 文件结构
data-processing/
├── README.md              # 本文档
├── data/                  
    ├── train.csv         # 已修复好的训练数据
    └── metadata.csv      # 已修复好的元数据

---

## 📊 最终数据集说明

### ✅ `metadata.csv` - 前端用（已上传至 `main/data/`）

| 字段 | 类型 | 说明 | 对应数据库表/字段 |
|------|------|------|------------------|
| `Title` | string | 书名 | `BOOKS.title` |
| `authors` | string | 作者 | `BOOKS.author` |
| `description` | text | 图书简介 | `BOOKS.description` |
| `image` | string | 封面图URL | `BOOK_IMAGES.image_url` |
| `categories` | string | 分类 | `CATEGORIES.name` |
| `avg_rating` | float | 平均评分 | `BOOKS.avg_rating` |
| `review_count` | int | 精选评论数 | `BOOKS.review_count` |
| `ratingsCount` | int | 亚马逊评分人数 | `BOOKS.ratings_count` |
| `Price` | float | 价格 | `BOOKS.base_price` |
| `publisher` | string | 出版社 | `BOOKS.publisher` |
| `publishedDate` | string | 出版日期 | `BOOKS.publish_date` |

**📌 规格**：250本书 | 0.5MB | 每本书1行

---

### ✅ `train.csv` - 模型训练用（已上传至 `main/data/`）

| 字段 | 类型 | 说明 | 对应数据库表/字段 |
|------|------|------|------------------|
| `Id` | string | 图书ISBN | `BOOKS.isbn` |
| `Title` | string | 书名 | `BOOKS.title` |
| `User_id` | string | 用户ID | `USERS.username` |
| `review/score` | int | 评分 | `REVIEWS.rating` |
| `review/text` | text | 评论内容 | `REVIEWS.comment` |
| `review/time` | int | 时间戳 | `REVIEWS.created_at` |
| `review/helpfulness` | string | 帮助率 | `REVIEWS.helpfulness` |
| `profileName` | string | 用户名 | `USERS.first_name` |

**📌 规格**：**3,527条**评论 | 19MB | 平均每本书**14.1条**

**✅ 数据质量控制：**
- 只保留 **帮助率 > 50%** 的高质量评论
- 已**去重**（同一用户同一条评论只保留一次）
- 同一本书价格**已统一**（取中位数）
- `authors`/`categories` **已提取第一个元素**

---

## 🗄️ 数据库导入映射

### `metadata.csv` → 数据库

| CSV字段 | 目标表 | 目标字段 |
|--------|-------|--------|
| `Id` | `BOOKS` | `isbn` |
| `Title` | `BOOKS` | `title` |
| `authors` | `BOOKS` | `author` |
| `description` | `BOOKS` | `description` |
| `Price` | `BOOKS` | `base_price` |
| `avg_rating` | `BOOKS` | `avg_rating` |
| `categories` | `CATEGORIES` | `name` |
| `image` | `BOOK_IMAGES` | `image_url` |

### `train.csv` → 数据库

| CSV字段 | 目标表 | 目标字段 |
|--------|-------|--------|
| `Id` | `BOOKS` | `isbn`（关联） |
| `User_id` | `USERS` | `username` |
| `review/score` | `REVIEWS` | `rating` |
| `review/text` | `REVIEWS` | `comment` |
| `review/time` | `REVIEWS` | `created_at` |

## 📚 References

1. **Amazon Books Reviews Dataset**  
   Mohamed Bakhet. (2023). *Amazon Books Reviews* [Data set]. Kaggle.  
   https://www.kaggle.com/datasets/mohamedbakhet/amazon-books-reviews

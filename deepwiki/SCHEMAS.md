# cli-web-deepwiki schemas

## AskAnswer

_Object containing the following properties:_

| Property            | Type                                                                                                                                                                                                                                                                                        |
| :------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`query_id`** (\*) | `string`                                                                                                                                                                                                                                                                                    |
| **`state`** (\*)    | `'pending' \| 'running' \| 'done' \| 'error'`                                                                                                                                                                                                                                               |
| `title`             | `string`                                                                                                                                                                                                                                                                                    |
| `markdown`          | `string`                                                                                                                                                                                                                                                                                    |
| `references`        | _Array of objects:_<ul><li><b><code>file_path</code></b> (\*): <code>string</code></li><li><code>range_start</code>: <code>number</code> (<i>int</i>)</li><li><code>range_end</code>: <code>number</code> (<i>int</i>)</li><li><code>url</code>: <code>string</code> (<i>url</i>)</li></ul> |

_(\*) Required._

## RepoIndex

_Object containing the following properties:_

| Property             | Type     |
| :------------------- | :------- |
| **`id`** (\*)        | `string` |
| **`owner`** (\*)     | `string` |
| **`name`** (\*)      | `string` |
| **`full_name`** (\*) | `string` |
| `short_commit_sha`   | `string` |
| `language`           | `string` |
| `last_indexed`       | `string` |
| `description`        | `string` |

_(\*) Required._

## Source

_Object containing the following properties:_

| Property       | Type                                                                                                |
| :------------- | :-------------------------------------------------------------------------------------------------- |
| `path`         | `string`                                                                                            |
| **`url`** (\*) | `string` (_url_)                                                                                    |
| `line_range`   | _Tuple:_<ol><li><code>number</code> (<i>int</i>)</li><li><code>number</code> (<i>int</i>)</li></ol> |
| `title`        | `string`                                                                                            |

_(\*) Required._

## StructureNode

_Object containing the following properties:_

| Property         | Type                  |
| :--------------- | :-------------------- |
| **`slug`** (\*)  | `string`              |
| **`title`** (\*) | `string`              |
| `parent`         | `string` (_nullable_) |

_(\*) Required._

## VaultIndex

_Object containing the following properties:_

| Property                | Type                                                                                                                                                |
| :---------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`repo`** (\*)         | `string`                                                                                                                                            |
| **`generated_at`** (\*) | `string`                                                                                                                                            |
| **`pages`** (\*)        | _Array of objects:_<ul><li><b><code>slug</code></b> (\*): <code>string</code></li><li><b><code>title</code></b> (\*): <code>string</code></li></ul> |
| **`structure`** (\*)    | _Array of_ [StructureNode](#structurenode) _items_                                                                                                  |

_(\*) Required._

## VaultPageFrontmatter

_Object containing the following properties:_

| Property         | Type                                 |
| :--------------- | :----------------------------------- |
| **`title`** (\*) | `string`                             |
| **`slug`** (\*)  | `string`                             |
| **`repo`** (\*)  | `string`                             |
| `indexed_at`     | `string`                             |
| `indexed_commit` | `string`                             |
| `sources`        | _Array of_ [Source](#source) _items_ |
| `deepwiki_url`   | `string` (_url_)                     |
| `tags`           | `Array<string>`                      |
| `fetched_at`     | `string`                             |

_(\*) Required._

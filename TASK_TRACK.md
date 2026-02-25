## **整体架构**

用户交互层 支持文字/ 语音两种输入方式

网关路由层 OpenClaw (Node.js) - 意图识别& 技能路由

业务逻辑层 xDP Agent Core (Python) - 导购核心逻辑

能力支撑层 ASR / NLU / RAG / Generation / TTS

<br />

## **进展与规划**

| 阶段      | 目标                                                    | 状态   |
| :------ | :---------------------------------------------------- | :--- |
| Phase 1 | 搭建基础架构，支持文本交互                                         | Done |
| Phase 2 | 接入xDP API语音能力（ASR/TTS）                                | WIP  |
| Phase 3 | 替换Mock 服务，接入真实模型（NLU/Planner）                         | Wait |
| Phase 4 | 接入商品库(demo)， end-to-end联调, 保证性能(若不满足性能将NLU LLM迁移到GPU) | Wait |

<br />

### **对于Phase 3 要替换的Mock服务**

| Skill      | 职责         | 状态                    |
| :--------- | :--------- | :-------------------- |
| ASR        | 语音→ 文字     | 已接入xDP  API           |
| NLU        | 意图识别+ 实体提取 | !当前为规则匹配（Mock）        |
| RAG        | 商品向量检索     | !当前为本地Embedding（Mock） |
| Generation | 对话生成       | !当前为模板填充（Mock）        |
| TTS        | 文字→ 语音     | !已接入xDP（待验证）          |
| Memory     | 对话历史& 用户画像 | 已实现JSON 存储            |

<br />

#### **对于其中的NLU skill, LLM(for xeon)如下：**

<br />

| Option                  | Configuration                 | Approach                                                                                | Best For              |
| :---------------------- | :---------------------------- | :-------------------------------------------------------------------------------------- | :-------------------- |
| **A. Lightweight**      | TextCNN/BERT-Tiny + Qwen 0.5B | Hybrid architecture:Traditional classifier for intent detection, small LLM for planning | Cost-sensitive pilots |
| **B. Balanced**         | Qwen2.5-1.5B-Instruct         | Unified single model                                                                    | Production deployment |
| **C. High-Performance** | Qwen2.5-3B-Instruct (INT4)    | Quantized large model                                                                   | Complex conversations |

### **DEMO用例**

场景：用户语音询问” 我长痘了，推荐个精华”

<br />

```
用户语音输入
1. [ASR Skill] 语音识别→ "我长痘了，推荐个精华"
2. [NLU Skill] 意图识别→ product_qa（商品咨询） 实体提取→ concern: 痘痘, product_type: 精华
3. [RAG Skill] 向量检索→ 返回「净痘修护精华」等候选商品
4. [Generation] 话术生成→ "宝子你这个问题问得太对了！ 可以优先看「净痘修护精华」..."
5. [Memory] 持久化→ 记录对话历史& 用户关注点
```


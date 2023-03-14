import json
import os
import traceback
import uuid
from copy import deepcopy
from flask import request, Flask
import openai
import requests
import backoff  # for exponential backoff
# completions_with_backoff(model="text-davinci-002", prompt="Once upon a time,")

from text_to_image import text_to_image

with open("config.json", "r",
          encoding='utf-8') as jsonfile:
    config_data = json.load(jsonfile)
    qq_no = config_data['qq_bot']['qq_no']

session_config = {
    'msg': [
        {"role": "system", "content": config_data['chatgpt']['preset']}
    ]
}

class RulesClass:

    def __init__(self):
        self.max_num = 0
        self.current_key_index = 0
        self.is_group = 1
        self.key_number = 1
        self.is_continue = 0
        self.is_administrator = 0

# openai.OpenAIError
chat_rules = RulesClass()

sessions = {}
chat_rules.key_number = len(config_data['openai']['api_key'])

# openai.api_base = "https://chat-gpt.aurorax.cloud/v1"

# 创建一个服务，把当前这个python文件当做一个服务
server = Flask(__name__)

@backoff.on_exception(backoff.expo, openai.error.RateLimitError)
def completions_with_backoff(**kwargs):
    return openai.Completion.create(**kwargs)

# 测试接口，可以测试本代码是否正常启动
@server.route('/', methods=["GET"])
def index():
    return f"你好，世界!<br/>"


# 获取账号余额接口
@server.route('/credit_summary', methods=["GET"])
def credit_summary():
    return get_credit_summary()


# qq消息上报接口，qq机器人监听到的消息内容将被上报到这里
@server.route('/', methods=["POST"])
def get_message():
    global chat_rules
    uid = request.get_json().get('sender').get('user_id')  # 获取信息发送者的 QQ号码
    message = request.get_json().get('raw_message')  # 获取原始信息

    if uid == '2281717797': # 判断是否管理员
        chat_rules.is_administrator = 1
    else:
        chat_rules.is_administrator = 0

    if request.get_json().get('message_type') == 'private':  # 如果是私聊信息
        sender = request.get_json().get('sender')  # 消息发送者的资料
        print("收到私聊消息：")
        print(message)
        # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
        if chat_rules.is_administrator:  # 判断是否管理员
            if message.strip().startswith('禁止群消息'):
                chat_rules.is_group = 0
                send_private_message(uid, '已禁止群消息')
            elif message.strip().startswith('允许群消息'):
                chat_rules.is_group = 1
                send_private_message(uid, '已允许群消息')
            elif message.strip().startswith('禁止群消息') or message.strip().startswith('允许群消息'):
                send_private_message(uid, '看起来你好像不是纯种猪喔')

        elif message.strip().startswith('生成图像'):
            message = str(message).replace('生成图像', '')
            msg_text = chat(message, 'P' + str(uid))  # 将消息转发给ChatGPT处理
            # 将ChatGPT的描述转换为图画
            print('开始生成图像')
            pic_path = get_openai_image(msg_text)
            send_private_message_image(uid, pic_path, msg_text)
        elif message.strip().startswith('直接生成图像'):
            message = str(message).replace('直接生成图像', '')
            print('开始直接生成图像')
            pic_path = get_openai_image(message)
            send_private_message_image(uid, pic_path, '')
        else:
            msg_text = chat(message, 'P' + str(uid))  # 将消息转发给ChatGPT处理
            send_private_message(uid, msg_text)  # 将消息返回的内容发送给用户

    if request.get_json().get('message_type') == 'group':  # 如果是群消息
        gid = request.get_json().get('group_id')  # 群号

        if chat_rules.is_administrator:  # 判断是否管理员
            if message.strip().startswith('禁止群消息'):
                chat_rules.is_group = 0
                send_group_message(gid, '已禁止群消息', uid)
            elif message.strip().startswith('允许群消息'):
                chat_rules.is_group = 1
                send_group_message(gid, '已允许群消息', uid)
            elif message.strip().startswith('禁止群消息') or message.strip().startswith('允许群消息'):
                send_group_message(gid, '看起来你好像不是纯种猪喔', uid)
        if chat_rules.is_group == 0:
            return 'group_no'
        # 判断当被@时才回答
        if str("[CQ:at,qq=%s]" % qq_no) in message:
            sender = request.get_json().get('sender')  # 消息发送者的资料
            print("收到群聊消息：")
            print(message)
            message = str(message).replace(str("[CQ:at,qq=%s]" % qq_no), '')
            if message.strip().startswith('生成图像'):
                message = str(message).replace('生成图像', '')
                # 将ChatGPT的描述转换为图画
                print('开始生成图像')
                pic_path = get_openai_image(message)
                send_group_message_image(gid, pic_path, uid)
            else:
                # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
                msg_text = chat(message, 'G' + str(gid))  # 将消息转发给ChatGPT处理
                send_group_message(gid, msg_text, uid)  # 将消息转发到群里

    if request.get_json().get('post_type') == 'request':  # 收到请求消息
        print("收到请求消息")
        request_type = request.get_json().get('request_type')  # group
        uid = request.get_json().get('user_id')
        flag = request.get_json().get('flag')
        comment = request.get_json().get('comment')
        print("配置文件 auto_confirm:" + str(config_data['qq_bot']['auto_confirm']) + " admin_qq: " + str(
            config_data['qq_bot']['admin_qq']))
        if request_type == "friend":
            print("收到加好友申请")
            print("QQ：", uid)
            print("验证信息", comment)
            # 如果配置文件里auto_confirm为 TRUE，则自动通过
            if config_data['qq_bot']['auto_confirm']:
                set_friend_add_request(flag, "true")
            else:
                if str(uid) == config_data['qq_bot']['admin_qq']:  # 否则只有管理员的好友请求会通过
                    print("管理员加好友请求，通过")
                    set_friend_add_request(flag, "true")
        if request_type == "group":
            print("收到群请求")
            sub_type = request.get_json().get('sub_type')  # 两种，一种的加群(当机器人为管理员的情况下)，一种是邀请入群
            gid = request.get_json().get('group_id')
            if sub_type == "add":
                # 如果机器人是管理员，会收到这种请求，请自行处理
                print("收到加群申请，不进行处理")
            elif sub_type == "invite":
                print("收到邀请入群申请")
                print("群号：", gid)
                # 如果配置文件里auto_confirm为 TRUE，则自动通过
                if config_data['qq_bot']['auto_confirm']:
                    set_group_invite_request(flag, "true")
                else:
                    if str(uid) == config_data['qq_bot']['admin_qq']:  # 否则只有管理员的拉群请求会通过
                        set_group_invite_request(flag, "true")
    return "ok"


# 测试接口，可以用来测试与ChatGPT的交互是否正常，用来排查问题
@server.route('/chat', methods=['post'])
def chatapi():
    requestJson = request.get_data()
    if requestJson is None or requestJson == "" or requestJson == {}:
        resu = {'code': 1, 'msg': '请求内容不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    data = json.loads(requestJson)
    if data.get('id') is None or data['id'] == "":
        resu = {'code': 1, 'msg': '会话id不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    print(data)
    try:
        msg = chat(data['msg'], data['id'])
        resu = {'code': 0, 'data': msg, 'id': data['id']}
        return json.dumps(resu, ensure_ascii=False)
    except Exception as error:
        print("接口报错")
        resu = {'code': 1, 'msg': '请求异常: ' + str(error)}
        return json.dumps(resu, ensure_ascii=False)


# 重置会话接口
@server.route('/reset_chat', methods=['post'])
def reset_chat():
    requestJson = request.get_data()
    if requestJson is None or requestJson == "" or requestJson == {}:
        resu = {'code': 1, 'msg': '请求内容不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    data = json.loads(requestJson)
    if data['id'] is None or data['id'] == "":
        resu = {'code': 1, 'msg': '会话id不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    # 获得对话session
    session = get_chat_session(data['id'])
    # 清除对话内容但保留人设
    del session['msg'][1:len(session['msg'])]
    resu = {'code': 0, 'msg': '重置成功'}
    return json.dumps(resu, ensure_ascii=False)


# 与ChatGPT交互的方法
def chat(msg, sessionid):
    global chat_rules
    try:
        if '快干活啦' == msg.strip():
            chat_rules.max_num = 0
            return '似乎有了一点活力...'
        if msg.strip() == '':
            return '你好鸭，我是猪猪!'
        # 获得对话session
        session = get_chat_session(sessionid)
        if '重置会话' == msg.strip():
            # 清除对话内容但保留人设
            del session['msg'][1:len(session['msg'])]
            return "会话已重置"
        if '重置人格' == msg.strip():
            # 清空对话内容并恢复预设人设
            session['msg'] = [
                {"role": "system", "content": config_data['chatgpt']['preset']}
            ]
            return '人格已重置'
        if '连续对话' == msg.strip():
            chat_rules.is_continue = 1
            return '连续对话模式已开启'
        if '单次对话' == msg.strip():
            chat_rules.is_continue = 0
            return '单次对话模式已开启'
        if '指令说明' == msg.strip():
            return "指令如下(群内需@机器人)：\n1.[重置会话]\n2.[设置人格] 请发送 设置人格+人格描述\n3.[重置人格]\n4.[指令说明]\n5.[禁止群消息]\n6.[允许群消息]\n7.[快干活啦]\n8.[单次对话]\n9.[连续对话]\n10.[生成图片]"
        if msg.strip().startswith('设置人格'):
            # 清空对话并设置人设
            session['msg'] = [
                {"role": "system", "content": msg.strip().replace('设置人格', '')}
            ]
            return '人格设置成功'
        # 设置本次对话内容
        session['msg'].append({"role": "user", "content": msg})
        # 与ChatGPT交互获得对话内容
        print(session['msg'])
        message = chat_with_gpt(session['msg'])
        print(message)
        # 查看是否出错
        if message.__contains__("The server had an error processing your request.") or \
        message.__contains__("That model is currently overloaded with other requests."):
            message = chat(msg, sessionid)

        if message.__contains__("This model's maximum context length is 4096 token"):
            del session['msg'][2:len(session['msg'])-2]
            # 去掉最后一条
            # del session['msg'][len(session['msg']) - 1:len(session['msg'])]
            # 重新交互
            message = chat(msg, sessionid)
        
        if chat_rules.is_continue:
            # 记录上下文
            session['msg'].append({"role": "assistant", "content": message})
        else:
            session['msg'].pop()
        print("会话ID: " + str(sessionid))
        print("ChatGPT返回内容: ")
        print(message)
        return message
    except Exception as error:
        traceback.print_exc()
        return str('异常: ' + str(error))


# 获取对话session
def get_chat_session(sessionid):
    if sessionid not in sessions:
        config = deepcopy(session_config)
        config['id'] = sessionid
        sessions[sessionid] = config
    return sessions[sessionid]


def chat_with_gpt(messages):
    global chat_rules
    if chat_rules.max_num == chat_rules.key_number:
        return '让我歇会嘛( ;ﾟдﾟ)'
    try:
        if not config_data['openai']['api_key']:
            return '请设置Api Key'
        else:
            openai.api_key = config_data['openai']['api_key'][chat_rules.current_key_index]
            # print(messages)
        # resp = completions_with_backoff(model=config_data['chatgpt']['model'], prompt=messages)
        resp = openai.ChatCompletion.create(
            model=config_data['chatgpt']['model'],
            messages=messages
        )
        resp = resp['choices'][0]['message']['content']
    except openai.OpenAIError as e:
        if str(e).__contains__("Rate limit reached for default-gpt-3.5-turbo"):
            # 切换key
            if chat_rules.current_key_index == chat_rules.key_number - 1:
                chat_rules.current_key_index = 0
            else:
                chat_rules.current_key_index = chat_rules.current_key_index + 1
                chat_rules.max_num = max_num + 1

            print("速率限制，尝试切换key")
           
            return chat_with_gpt(messages)
        else:
            print('openai 接口报错: ' + str(e))
            resp = str(e)
    chat_rules.max_num = 0
    print(openai.OpenAIError)
    return resp


# 生成图片
def genImg(message):
    img = text_to_image(message)
    filename = str(uuid.uuid1()) + ".png"
    filepath = config_data['qq_bot']['image_path'] + str(os.path.sep) + filename
    img.save(filepath)
    print("图片生成完毕: " + filepath)
    return filename


# 发送私聊消息方法 uid为qq号，message为消息内容
def send_private_message(uid, message):
    try:
        if len(message) >= config_data['qq_bot']['max_length']:  # 如果消息长度超过限制，转成图片发送
            pic_path = genImg(message)
            message = "[CQ:image,file=" + pic_path + "]"
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_private_msg",
                            params={'user_id': int(uid), 'message': message}).json()
        if res["status"] == "ok":
            print("私聊消息发送成功")
        else:
            print(res)
            print("私聊消息发送失败，错误信息：" + str(res['wording']))

    except Exception as error:
        print("私聊消息发送失败")
        print(error)


# 发送私聊消息方法 uid为qq号，pic_path为图片地址
def send_private_message_image(uid, pic_path, msg):
    try:
        message = "[CQ:image,file=" + pic_path + "]"
        if msg != "":
            message = msg + '\n' + message
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_private_msg",
                            params={'user_id': int(uid), 'message': message}).json()
        if res["status"] == "ok":
            print("私聊消息发送成功")
        else:
            print(res)
            print("私聊消息发送失败，错误信息：" + str(res['wording']))

    except Exception as error:
        print("私聊消息发送失败")
        print(error)


# 发送群消息方法
def send_group_message(gid, message, uid):
    try:
        if len(message) >= config_data['qq_bot']['max_length']:  # 如果消息长度超过限制，转成图片发送
            pic_path = genImg(message)
            message = "[CQ:image,file=" + pic_path + "]"
        message = str('[CQ:at,qq=%s]\n' % uid) + message  # @发言人
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_group_msg",
                            params={'group_id': int(gid), 'message': message}).json()
        if res["status"] == "ok":
            print("群消息发送成功")
        else:
            print("群消息发送失败，错误信息：" + str(res['wording']))
    except Exception as error:
        print("群消息发送失败")
        print(error)


# 发送群消息图片方法
def send_group_message_image(gid, pic_path, uid, msg):
    try:
        message = "[CQ:image,file=" + pic_path + "]"
        if msg != "":
            message = msg + '\n' + message
        message = str('[CQ:at,qq=%s]\n' % uid) + message  # @发言人
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_group_msg",
                            params={'group_id': int(gid), 'message': message}).json()
        if res["status"] == "ok":
            print("群消息发送成功")
        else:
            print("群消息发送失败，错误信息：" + str(res['wording']))
    except Exception as error:
        print("群消息发送失败")
        print(error)


# 处理好友请求
def set_friend_add_request(flag, approve):
    try:
        requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/set_friend_add_request",
                      params={'flag': flag, 'approve': approve})
        print("处理好友申请成功")
    except:
        print("处理好友申请失败")


# 处理邀请加群请求
def set_group_invite_request(flag, approve):
    try:
        requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/set_group_add_request",
                      params={'flag': flag, 'sub_type': 'invite', 'approve': approve})
        print("处理群申请成功")
    except:
        print("处理群申请失败")


# openai生成图片
def get_openai_image(des):
    global chat_rules
    openai.api_key = config_data['openai']['api_key'][chat_rules.current_key_index]
    response = openai.Image.create(
        prompt=des,
        n=1,
        size=config_data['openai']['img_size']
    )
    image_url = response['data'][0]['url']
    print('图像已生成')
    print(image_url)
    return image_url


# 查询账户余额
def get_credit_summary():
    global chat_rules
    url = "https://chat-gpt.aurorax.cloud/dashboard/billing/credit_grants"
    res = requests.get(url, headers={
        "Authorization": f"Bearer " + config_data['openai']['api_key'][chat_rules.current_key_index]
    }, timeout=60).json()
    return res


if __name__ == '__main__':
    server.run(port=5555, host='0.0.0.0', use_reloader=False)

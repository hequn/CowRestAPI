#!/usr/bin/env python
import os
from flask import Flask, abort, request, jsonify, g, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_httpauth import HTTPBasicAuth
from passlib.apps import custom_app_context as pwd_context
from itsdangerous import (TimedJSONWebSignatureSerializer
                          as Serializer, BadSignature, SignatureExpired)
import cv2
import numpy
import base64
from PIL import Image
from io import BytesIO
import utils
import json
import config
import datetime
import logging.config
import glob
import shutil

if not os.path.exists('logs'):
    os.mkdir('logs')
logging.config.fileConfig(os.path.join(os.path.dirname(os.path.abspath(__file__)), r"log.conf"), defaults=None,
                          disable_existing_loggers=True)
logger = logging.getLogger("log")

# DOCS https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(4)

# initialization
app = Flask(__name__)
app.config.from_object("config")

# extensions
db = SQLAlchemy(app)
auth = HTTPBasicAuth()


class User(db.Model):
    """
    The User class, userid/passwd and company_id are required.
    """
    __tablename__ = 'users'
    userid = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.String(32), index=True)
    password_hash = db.Column(db.String(120))

    def hash_password(self, password):
        """
        Secure the passwd using hash encrypt.
        :param password:
        :return: the hash pwd
        """
        self.password_hash = pwd_context.encrypt(password)

    def verify_password(self, password):
        """
         verify password
        :param password:
        :return:
        """
        return pwd_context.verify(password, self.password_hash)

    def generate_auth_token(self, expiration=600):
        """
         generate token
        :param expiration: set expiration time
        :return:
        """
        s = Serializer(config.SECRET_KEY, expires_in=expiration)
        return s.dumps({'userid': self.userid})

    @staticmethod
    def verify_auth_token(token):
        """
         get users by token
        :param token:
        :return:
        """
        s = Serializer(config.SECRET_KEY)
        try:
            data = s.loads(token)
        except SignatureExpired:
            return None  # valid token, but expired
        except BadSignature:
            return None  # invalid token
        user = User.query.get(data['userid'])
        return user


class LogInfo(db.Model):
    """
    The logs class
    """
    __tablename__ = 'log_info'
    log_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id = db.Column(db.String(32))
    remote_ip = db.Column(db.String(32))
    rfid_code = db.Column(db.String(32))
    imei = db.Column(db.String(64))
    extra_info = db.Column(db.String(64), nullable=True)


class Archives(db.Model):
    """
    The archives class
    """
    __tablename__ = 'archives'
    aid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    rfid_code = db.Column(db.String(32))
    age = db.Column(db.Integer)
    company_id = db.Column(db.String(32))
    gather_time = db.Column(db.DateTime)
    folder_path = db.Column(db.String(200))
    health_status = db.Column(db.String(32))
    extra_info = db.Column(db.String(64), nullable=True)


@auth.verify_password
def verify_password(userid_or_token, password):
    # first try to authenticate by token
    user = User.verify_auth_token(userid_or_token)
    if not user:
        # try to authenticate with username/password
        user = User.query.filter_by(userid=userid_or_token).first()
        if not user or not user.verify_password(password):
            return False
    g.user = user
    return True


################################################
# Error Handling
################################################


@app.errorhandler(400)
def error_400(error):
    """
     verification of input parameters
    :param error: error message
    :return: exception message
    """
    return jsonify({"status": "1x0000", "message": "{} param not right".format(error.description)})


@app.errorhandler(403)
def error_403(error):
    """
     about data repetition errors
    :param error:
    :return: exception message
    """
    return jsonify({"status": "5x0001", "message": "Data already exists"})


@app.errorhandler(404)
def error_404(error):
    return jsonify({"status": "8x0001", "message": "Accessed resources do not exist"})


@app.errorhandler(405)
def error_405(error):
    return str(error)


@app.errorhandler(413)
def error_413(error):
    return jsonify({"status": "6x0001", "message": "Video size needs to be less than 20MB"})


@app.errorhandler(500)
def error_500(error):
    return str(error)


@app.errorhandler(502)
def error_502(error):
    """
     about database operation error
    :param error:
    :return: exception message
    """
    return jsonify({"status": "3x0000", "message": "database operation error"})


@app.errorhandler(501)
def error_501(error):
    return jsonify({"status": "7x0001", "message": "Video Interception Picture Failed"})


###############################################
# Route Handling
###############################################


@app.route('/api/add_user', methods=['POST'])
def new_user():
    """
    Add the user to the db.
    :return:
    """
    userid = request.json.get('userid')
    password = request.json.get('password')
    company_id = request.json.get('companyid')
    # verify the existence of parameters
    utils.verify_param(abort, logger, error_code=400, userid=userid, password=password, company_id=company_id,
                       method_name="new_user")
    if User.query.filter_by(userid=userid).first() is not None:
        logger.error("userid = {} already exists and cannot be added repeatedly".format(userid))
        abort(403)  # existing user
    user = User(userid=userid, company_id=company_id)
    user.hash_password(password)
    try:
        db.session.add(user)
        db.session.commit()
        logger.info("Database insert user(userid={},company_id={}) succeeded".format(userid, company_id))
    except:
        logger.error("failure to store user(userid={},company_id={}) to database".format(userid, company_id))
        abort(502)
    return (jsonify({'userid': user.userid, 'company_id': user.company_id}), 201,
            {'Location': url_for('get_user', userid=user.userid, _external=True)})


@app.route('/api/login', methods=['POST'])
def login():
    """
    User login
    :return: companyid
    """
    userid = request.json.get('userid')
    password = request.json.get('password')
    # verify the existence of parameters
    utils.verify_param(abort, logger, error_code=400, userid=userid, password=password, method_name="login")
    user = User.query.filter_by(userid=userid).first()
    if user:
        if user.verify_password(password):
            # If the userid and password is correct, return company_id
            company_id = User.query.filter_by(userid=userid).first().company_id
        else:
            # returned to empty incorrectly
            company_id = ""
    else:
        company_id = ""
    return (jsonify({'companyid': company_id}))


@app.route('/api/users/<int:userid>')
def get_user(userid):
    """
    Get the user by id.
    :param userid: user ID
    :return: userid
    """
    user = User.query.get(userid)
    if user:
        return jsonify({'userid': user.userid})
    else:
        logger.error("No user with userid = {} exists".format(userid))
        abort(502)


@app.route('/api/token')
@auth.login_required
def get_auth_token():
    """
     get token
    :return: token message and duration time
    """
    token = g.user.generate_auth_token(600)
    return jsonify({'token': token.decode('ascii'), 'duration': 600})


@app.route('/api/prospect', methods=['POST'])
@auth.login_required
def prospect():
    """
     get the predicted results based on message
    :return: predicted results and cow information
    """
    user_id = g.user.userid
    company_id = request.json.get('companyid')
    gather_time1 = request.json.get('gathertime')
    gather_time = utils.verify_time_param(abort, logger, gather_time1)
    rfid_code = request.json.get('rfidcode')
    ip = request.json.get('ip')
    imei = request.json.get('imei')
    image_array = request.json.get('items')
    predict_array = []
    cid_array = []
    # verify the existence of parameters
    utils.verify_param(abort, logger, error_code=400, user_id=user_id, company_id=company_id, gather_time=gather_time,
                       rfid_code=rfid_code, ip=ip, imei=imei, image_array=image_array, method_name="prospect")
    for i, item in enumerate(image_array):
        # get the base64 str and decode them to image
        img_base64 = item.get('cvalue')
        img_oriented = item.get('cid')
        starter = img_base64.find(',')
        img_base64 = img_base64[starter + 1:]
        bytes_buffer = BytesIO(base64.b64decode(img_base64))
        # get one for pillow and another for
        img_pillow = Image.open(bytes_buffer)
        img_pillow1 = img_pillow.resize(config.img_size, Image.NEAREST)
        img_pillow2 = numpy.array(img_pillow1).astype(numpy.float32)

        # img_cv2 = cv2.imdecode(numpy.frombuffer(bytes_buffer.getvalue(), numpy.uint8), cv2.IMREAD_COLOR)
        # img_cv2 = cv2.resize(img_cv2, config.img_size)

        predict_array.append(img_pillow2)
        cid_array.append(img_oriented)

    # get the predicted results and returned
    result, predict_code = utils.get_predicted_result(predict_array, cid_array)
    if rfid_code == predict_code and result >= config.min_predict:
        resoult = 1
        logger.info(
            "From ip {} -> cow rfid_code = {},company_id = {} prediction success,result = {}%".format(ip, rfid_code,
                                                                                                      company_id,
                                                                                                      result))
    else:
        resoult = 0
        logger.info(
            "From ip {} -> cow rfid_code = {},company_id = {} prediction failure,result = {}%".format(ip, rfid_code,
                                                                                                      company_id,
                                                                                                      result))

    # get the previous registered images top3 and encode them to base64
    pre_files = utils.get_files(os.path.join(config.base_images_path, company_id, predict_code) + os.sep, 3)
    pre_items = utils.read_image_to_base64(pre_files)

    return jsonify({
        'userid': user_id,
        'companyid': company_id,
        'resoult': resoult,
        'gathertime': str(gather_time),
        'percent': "predict_code:{},percent:{}%".format(predict_code, result),
        'verinfo': 'test',
        'ip': ip,
        'imei': imei,
        'items': pre_items
    })


@app.route('/api/verify', methods=['POST'])
@auth.login_required
def verify():
    """
     verify params and save the cow information to the db
    :return: cow information
    """
    # get the params first
    user_id = g.user.userid
    entity = request.form.get('entity')
    utils.verify_param(abort, logger, error_code=400, entity=entity, method_name="verify")
    json_obj = json.loads(entity)
    company_id = json_obj.get('companyid')
    gather_time1 = json_obj.get('gathertime')
    gather_time = utils.verify_time_param(abort, logger, gather_time1)
    rfid_code = json_obj.get('rfidcode')
    ip = json_obj.get('ip')
    imei = json_obj.get('imei')
    xvalue = json_obj.get('xvalue')
    yvalue = json_obj.get('yvalue')
    width = json_obj.get('width')
    height = json_obj.get('height')
    try:
        video = request.files['video']
    except:
        video = None
    # give the age value, 0 for default now.
    age = 0  # json_obj.get("age")
    # give the health_status value, 1 for default now.
    health_status = '1'  # json_obj.get("health_status")
    # verify the existence of parameters
    utils.verify_param(abort, logger, error_code=400, user_id=user_id, json_obj=json_obj, company_id=company_id,
                       gather_time=gather_time, rfid_code=rfid_code, ip=ip, imei=imei, xvalue=xvalue,
                       yvalue=yvalue, width=width, height=height, video=video, age=age, health_status=health_status,
                       method_name="verify")

    # judge the existence of cow
    if Archives.query.filter_by(rfid_code=rfid_code, company_id=company_id).first():
        logger.error("cow rfid_code = {} already exists and cannot be save repeatedly".format(rfid_code))
        abort(403)
    else:
        # Judging video size
        video_size = len(video.read()) / float(1000.0)
        if video_size > config.max_video_size:
            logger.error(
                'From ' + ip + ' -> Upload video file : ' + video.filename + ' with size of {} kb , But video_size over 20MB failed to upload'.format(
                    video_size))
            abort(413)
        # make the save folder path and save the video
        folder_path = os.path.join(config.base_images_path, company_id, rfid_code) + os.sep
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        video.seek(0)
        video.save(folder_path + utils.secure_filename(video.filename))
        logger.info('From ' + ip + ' -> Upload video file : ' + video.filename + ' with size of {} kb'.format(
            video_size))

        # make async execution thread for the video save and frame grabber
        executor.submit(utils.process_video_to_image, abort, logger, video, folder_path, rfid_code, xvalue, yvalue,
                        width,
                        height)
        # assign values to database fields
        archives = Archives(rfid_code=rfid_code, age=age, company_id=company_id, gather_time=gather_time,
                            health_status=health_status,
                            folder_path=os.path.join(config.base_images_path, company_id, rfid_code),
                            extra_info='file name is : ' + video.filename)
        li = LogInfo(company_id=company_id, rfid_code=rfid_code, remote_ip=ip, imei=imei,
                     extra_info='file name is : ' + video.filename)
        db_list = [archives, li]
        # logs the submit info to the db
        utils.insert_record(logger, db_list, db, abort, company_id, rfid_code, folder_path)
        logger.info(
            "cow rfid_code = {} from company_id = {} was successfully inserted into the database".format(rfid_code,
                                                                                                         company_id))
        return jsonify({
            'userid': user_id,
            'companyid': company_id,
            'resoult': True,
            'gathertime': str(gather_time),
            'verinfo': 'jobs was launched in background',
            'ip': ip,
            'imei': imei,
        })


@app.route('/api/list', methods=['POST'])
@auth.login_required
def cow_list_by_company_id():
    """
     Query the cows of the corresponding company
    :return: cow_list
    """

    def json_serilize(instance):
        """
         change the returned data to dict
        :param instance: data
        :return: message dict
        """
        # Get registered images and encode them to base64
        pre_files = utils.get_files(
            os.path.join(config.base_images_path, instance.company_id, instance.rfid_code) + os.sep, 1)
        pre_items = utils.read_image_to_base64(pre_files)
        return {
            "userid": g.user.userid,
            "aid": instance.aid,
            "rfid_code": instance.rfid_code,
            "age": instance.age,
            "company_id": instance.company_id,
            "gather_time": str(instance.gather_time),
            "health_status": instance.health_status,
            "extra_info": instance.extra_info,
            "items": pre_items
        }

    current_page = request.json.get("currentpage")
    cow_number = request.json.get("cownumber")
    company_id = request.json.get("companyid")
    utils.verify_param(abort, logger, error_code=400, company_id=company_id, method_name="cow_list_by_company_id")
    try:
        # get a list of cowrest based on the current page number and display number
        if current_page and cow_number:
            cow_list = Archives.query.filter_by(company_id=company_id).paginate(page=current_page,
                                                                                per_page=cow_number).items
        else:
            # return all cows list without current page or display number
            cow_list = Archives.query.filter_by(company_id=company_id).all()
        return json.dumps(cow_list, default=json_serilize)
    except:
        logger.error("Database query cow list failed")
        abort(502)


@app.route('/api/verify_cow_exists', methods=['POST'])
@auth.login_required
def verify_cow_exists():
    """
     verify the existence of cow
    :return:
    """
    user_id = g.user.userid
    company_id = request.json.get('companyid')
    rfid_code = request.json.get('rfidcode')

    utils.verify_param(abort, logger, error_code=400, user_id=user_id, company_id=company_id, rfid_code=rfid_code,
                       method_name="verify_cow_exists")
    if Archives.query.filter_by(rfid_code=rfid_code, company_id=company_id).first():
        logger.info("cow rfid_code={} from company_id={} already exist in the Archives".format(rfid_code, company_id))
        result = True
    else:
        logger.info("cow rfid_code={} from company_id={} not exist in the Archives".format(rfid_code, company_id))
        result = False
    return jsonify({
        'userid': user_id,
        'companyid': company_id,
        'rfid_code': rfid_code,
        'result': result
    })


@app.route('/api/list_detail', methods=['POST'])
@auth.login_required
def list_detail():
    """
     Preview the picture of cow
    :return: image base64
    """
    company_id = request.json.get('companyid')
    rfid_code = request.json.get('rfidcode')

    utils.verify_param(abort, logger, error_code=400, company_id=company_id, rfid_code=rfid_code,
                       method_name="list_detail")
    pic_path = os.path.join(config.base_images_path, company_id, rfid_code) + os.sep
    pre_files = glob.glob(pic_path + '*.jpg')
    pic_num = len(pre_files)
    if pic_num > 0:
        step = pic_num // 10
        if step == 0:
            step = 1
        pre_items = utils.read_image_to_base64(pre_files[0:pic_num:step])
        return jsonify({
            "items": pre_items
        })
    else:
        logger.error("Folder {} not exist or No picture".format(pic_path))
        abort(404)


@app.route('/api/delete_pic', methods=['POST'])
@auth.login_required
def delete_pic():
    """
    Delete folders with poor image quality
    :return:
    """
    company_id = request.json.get('companyid')
    rfid_code = request.json.get('rfidcode')

    utils.verify_param(abort, logger, error_code=400, company_id=company_id, rfid_code=rfid_code,
                       method_name="delete_pic")

    user_id = g.user.userid
    if User.query.filter_by(userid=user_id).first().company_id != company_id:
        result = False
    else:
        cow = Archives.query.filter_by(rfid_code=rfid_code, company_id=company_id).first()
        cow2 = LogInfo.query.filter_by(rfid_code=rfid_code, company_id=company_id).first()
        folder_path = os.path.join(config.base_images_path, company_id, rfid_code) + os.sep
        if cow and cow2:
            try:
                db.session.delete(cow)
                db.session.delete(cow2)
                db.session.commit()
                shutil.rmtree(folder_path)
                logger.info("cow rfid_code={} from company_id={} Delete successful".format(rfid_code, company_id))
                result = True
            except:
                db.session.rollback()
                logger.error("cow rfid_code={} from company_id={} Delete failed".format(rfid_code, company_id))
                result = False
        else:
            logger.info("cow rfid_code={} from company_id={} not exist in the Database".format(rfid_code, company_id))
            result = False
    return jsonify({
        'companyid': company_id,
        'rfidcode': rfid_code,
        'result': result
    })


# the main entry when using flask only, of course you should use uwsgi instead in deploy environment.
if __name__ == '__main__':
    if not os.path.exists('db.sqlite'):
        db.create_all()
    app.run(host='0.0.0.0', debug=True)

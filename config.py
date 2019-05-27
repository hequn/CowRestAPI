import os
SECRET_KEY = 'the beijing telecom research center'
#If you want to switch databases，Here are two options（sqlite or mysql）
SQLALCHEMY_DATABASE_URI= 'sqlite:///db.sqlite'
# SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://root:XXXXXX@localhost:3306/cowrest'
SQLALCHEMY_COMMIT_ON_TEARDOWN = True
SQLALCHEMY_TRACK_MODIFICATIONS = True
# Mysql config POOL_SIZE and POOL_TIMEOUT
# SQLALCHEMY_POOL_SIZE=5
# SQLALCHEMY_POOL_TIMEOUT=10
base_images_path=os.path.join(os.path.dirname(os.path.abspath(__file__)) ,r"test")
batch_size = 100
model = None
classes = []
img_size = (299, 299)
noveltyDetectionLayerName = "fc1"
noveltyDetectionLayerSize = 1024
isCenterLoss = None
isTripletLoss = None
min_predict = 95.00
max_video_size=20000

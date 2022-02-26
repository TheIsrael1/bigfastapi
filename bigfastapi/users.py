from typing import Optional
from unicodedata import name
from fastapi.staticfiles import StaticFiles
from uuid import uuid4
import fastapi as fastapi
import os

import passlib.hash as _hash
from bigfastapi.models import user_models, auth_models
from fastapi import APIRouter, HTTPException, UploadFile, File
import sqlalchemy.orm as orm
from bigfastapi.db.database import get_db
from .schemas import users_schemas as _schemas
from .auth_api import is_authenticated, send_code_password_reset_email,  resend_token_verification_mail, verify_user_token, password_change_token
from .files import upload_image
from .email import send_invite_email
from .models import store_invite_model, store_user_model

app = APIRouter(tags=["User"])

# app.mount('static', StaticFiles(directory="static"), name='static')



@app.get("/users/me", response_model=_schemas.User)
async def get_user(user: _schemas.User= fastapi.Depends(is_authenticated)):
    return user


@app.put("/users/me")
async def update_user(
    user_update: _schemas.UserUpdate,
    user: _schemas.User = fastapi.Depends(is_authenticated),
    db: orm.Session = fastapi.Depends(get_db),
    ):
    return await user_update(user_update, user, db)



#user must be a super user to perform this
@app.put("/users/{user_id}/activate")
async def activate_user(user_activate: _schemas.UserActivate, user_id: str, user: _schemas.User = fastapi.Depends(is_authenticated),
    db: orm.Session = fastapi.Depends(get_db)):
    if user.is_superuser == False:
        raise fastapi.HTTPException(status_code=403, detail="only super admins can perform this operation")
    user_act = await get_user(db, id=user_id)
    if user.is_active == True:
        raise fastapi.HTTPException(status_code=403, detail="this user is already active")
    await activate(user_activate, user_id, db)
    

@app.post("/users/recover-password")
async def recover_password(email: _schemas.UserRecoverPassword, db: orm.Session = fastapi.Depends(get_db)):
    user = await get_user(db=db, email = email.email)
    await delete_password_reset_code(db, user.id)
    await send_code_password_reset_email(email.email, db)
    return f"password reset code has been sent to {email.email}"



@app.post("/users/reset-password")
async def reset_password(user: _schemas.UserResetPassword, db: orm.Session = fastapi.Depends(get_db)):
    code_exist = await get_password_reset_code_sent_to_email(user.code, db)
    if code_exist is None:
        raise fastapi.HTTPException(status_code=403, detail="invalid code")
    return await resetpassword(user, code_exist.user_id, db)


@app.put('/users/profile/update')
async def updateUserProfile(
    payload: _schemas.UpdateUserReq, 
    db: orm.Session = fastapi.Depends(get_db),
    user: str = fastapi.Depends(is_authenticated)):
    
    updatedUser = await updateUserDetails(db, user.id, payload)
    return {"data": updatedUser}


@app.patch('/users/password/update')
async def updateUserPassword(
    payload:_schemas.updatePasswordRequest,
    db: orm.Session = fastapi.Depends(get_db),
    user: str = fastapi.Depends(is_authenticated)):
    
    dbResponse = await updateUserPassword(db, user.id, payload)
    return {"data":  dbResponse }

@app.post('/users/accept-invite')
def accept_invite(
        payload:_schemas.StoreUser, 
        token:str, 
        db: orm.Session =fastapi.Depends(get_db)):
    # create store user
    store_user = store_user_model.StoreUser(
        store_id = payload.organization_id,
        user_id = payload.user_id,
        role = payload.role
    )
    db.add(store_user)
    db.commit()
    db.refresh(store_user)

@app.post("/users/invite/", status_code=201)
async def invite_user(
    payload: _schemas.UserInvite,
    app_url: str,
    template: Optional[str] = "invite_email.html",
    db: orm.Session = fastapi.Depends(get_db)
    ):
    """
        An endpoint to invite users to a store.

        Returns dict: message
    """

    try:
        invite_token = uuid4().hex
        invite_url = f"{app_url}/accept-invite?code={invite_token}"         

        email_details = {
        "subject": f"Invitation to {payload.store.name}",
        "recipient": payload.user_email,
        "title": f"Invitation to {payload.store.name}",
        "first_name": "",
        "body": payload.store.name,
        "link": invite_url
        }
        # send invite email to user
        is_sent = send_invite_email(email_details=email_details, template=template, db=db)
        if(is_sent):
            invite = store_invite_model.StoreInvite(
                store_id = payload.store.id,
                user_id = payload.user_id,
                user_email = payload.user_email,
                user_role = payload.user_role
            )
            db.add(invite)
            db.commit()
            db.refresh(invite)
            return is_sent
        return { "message": "An error occurred while sending invite email" }

    except:
        return { "message": "An error occcured while inviting user" }
        



# ////////////////////////////////////////////////////CODE ////////////////////////////////////////////////////////////// 

# @app.post("/users/verify/code/{code}")
# async def verify_user_with_code(
#     code: str,
#     db: orm.Session = fastapi.Depends(get_db),
#     ):
#     return await verify_user_code(code)



# ////////////////////////////////////////////////////CODE //////////////////////////////////////////////////////////////



# ////////////////////////////////////////////////////TOKEN ////////////////////////////////////////////////////////////// 
@app.post("/users/resend-verification/token")
async def resend_token_verification(
    email : _schemas.UserTokenVerification,
    db: orm.Session = fastapi.Depends(get_db),
    ):
    return await  resend_token_verification_mail(email.email, email.redirect_url, db)


@app.post("/users/verify/token/{token}")
async def verify_user_with_token(
    token: str,
    db: orm.Session = fastapi.Depends(get_db),
    ):
    return await verify_user_token(token)


@app.put("/users/password-change/token/{token}")
async def password_change_with_token(
    password : _schemas.UserPasswordUpdate,
    token: str,
    db: orm.Session = fastapi.Depends(get_db),
    ):
    return await password_change_token(password, token, db)


@app.put("/users/{user_id}/image")
async def user_image_upload(user_id: str, file: UploadFile = File(...), db: orm.Session = fastapi.Depends(get_db)):
    user = await get_user(db, id=user_id)
    image = await upload_image(file, db, bucket_name = user_id)
    filename = f"\\{user_id}\\{image}"
    root_location = os.path.abspath("filestorage")
    full_image_path =  root_location + filename
    user.image = full_image_path
    db.commit()
    db.refresh(user)
    return "successfully updated profile image"
   


# ////////////////////////////////////////////////////TOKEN //////////////////////////////////////////////////////////////

async def get_password_reset_code_sent_to_email(code: str, db: orm.Session):
    return db.query(auth_models.PasswordResetCode).filter(auth_models.PasswordResetCode.code == code).first()


   
async def user_update(user_update: _schemas.UserUpdate, user:_schemas.User, db: orm.Session):
    user = await get_user(db=db, id = user.id)

    if user_update.first_name != "":
        user.first_name = user_update.first_name

    if user_update.last_name != "":
        user.last_name = user_update.last_name

    if user_update.phone_number != "":
        user.phone_number = user_update.phone_number
    

    db.commit()
    db.refresh(user)

    return _schemas.User.fromorm(user)


async def activate(user_activate: _schemas.UserActivate, user:_schemas.User, db: orm.Session):
    user = await get_user(db=db, id = user_activate.email)
    user_activate.is_activte = True
    db.commit()
    db.refresh(user)

    return _schemas.User.fromorm(user)


async def deactivate(user_activate: _schemas.UserActivate, user:_schemas.User, db: orm.Session):
    user = await get_user(db=db, email = user_activate.email)
    user_activate.is_active = False
    db.commit()
    db.refresh(user)
    return _schemas.User.fromorm(user)




async def resetpassword(user: _schemas.UserResetPassword, id: str, db: orm.Session):
    user_found = await get_user(db, id = id)
    user_found.password = _hash.sha256_crypt.hash(user.password)
    db.query(auth_models.PasswordResetCode).filter(auth_models.PasswordResetCode.user_id == user_found.id).delete()
    db.commit()
    db.refresh(user_found)
    return "password reset successful"


async def get_user(db: orm.Session, email="", id=""):
    if email != "":
        return db.query(user_models.User).filter(user_models.User.email == email).first()
    if id != "":
        return db.query(user_models.User).filter(user_models.User.id == id).first()


async def delete_password_reset_code(db: orm.Session, user_id: str):
    db.query(auth_models.PasswordResetCode).filter(auth_models.PasswordResetCode.user_id == user_id).delete()
    db.commit()
    
    
# Update user profile/Bio    
async def updateUserDetails(db: orm.Session, userId:str, payload:_schemas.UpdateUserReq):
    user = db.query(user_models.User).filter(user_models.User.id == userId).first()
        
    user.first_name = payload.first_name
    user.last_name = payload.last_name
    user.email = payload.email
    user.country_code = payload.country_code
    user.phone_number = payload.phone_number
    user.country = payload.country
        
    try:
        db.commit()
        db.refresh(user)
        return user
    except:
        raise HTTPException( status_code=500, detail='Something went wrong')   
   
    
# Update user profile/Bio 
async def updateUserPassword(db: orm.Session, userId:str, payload: _schemas.updatePasswordRequest):
    if payload.password == payload.password_confirmation:
        user = db.query(user_models.User).filter(user_models.User.id == userId).first()
        user.password = _hash.sha256_crypt.hash(payload.password)
        
        try:
            db.commit()
            db.refresh(user)
            return user
        except :
            raise HTTPException( status_code=500, detail='Something went wrong')        
    else:
        raise HTTPException(status_code=422, detail='Password does not match')
        

def userinfo(claims, user):
    claims["email"] = user.email
    claims["email_verified"] = True
    claims["name"] = user.get_full_name() or user.username
    claims["preferred_username"] = user.username
    return claims

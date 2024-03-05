from django.shortcuts import redirect


def redirect_view(request, target: str):
    return redirect(target)
